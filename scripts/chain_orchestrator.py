#!/usr/bin/env python3
"""Chain orchestration engine for multi-step investigative follow-ups."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from time import perf_counter
from typing import Any

from chain_steps import STEP_REGISTRY
from log_utils import log


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_evidence_count(step_result: dict[str, Any]) -> int:
    output = step_result.get("output") if isinstance(step_result.get("output"), dict) else {}
    if isinstance(output.get("evidence_count"), int):
        return int(output.get("evidence_count"))
    if isinstance(output.get("evidence"), list):
        return len(output.get("evidence"))
    if isinstance(output.get("sample_examples"), list):
        return len(output.get("sample_examples"))
    return 0


def should_continue(step_result: dict[str, Any], policy: dict[str, Any]) -> bool:
    """Return whether chain execution should continue.

    Decision combines confidence deltas, evidence count, and remaining budget.
    """

    if not bool(step_result.get("continue_flag", True)):
        return False

    budget_remaining = _safe_float(policy.get("budget_usd"), 0.0) - _safe_float(policy.get("cost_spent"), 0.0)
    if budget_remaining <= 0:
        return False

    confidence = _safe_float(step_result.get("confidence"), 0.0)
    previous_confidence = _safe_float(policy.get("previous_confidence"), 0.0)
    confidence_delta = confidence - previous_confidence
    min_delta = _safe_float(policy.get("min_confidence_delta"), 0.05)

    evidence_count = _extract_evidence_count(step_result)
    min_evidence = _safe_int(policy.get("min_evidence_count"), 1)
    confidence_floor = _safe_float(policy.get("min_confidence_floor"), 0.35)

    if confidence_delta >= min_delta:
        return True

    if evidence_count >= min_evidence and confidence >= confidence_floor:
        return True

    return False


def _merge_policy(chain_def: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    overrides = chain_def.get("policy_overrides") if isinstance(chain_def.get("policy_overrides"), dict) else {}
    policy = {
        "max_depth": _safe_int(config.get("chain_max_depth"), 2),
        "max_branches": _safe_int(config.get("chain_max_branches"), 2),
        "timeout_sec": _safe_int(config.get("chain_timeout_sec"), 45),
        "budget_usd": _safe_float(config.get("chain_budget_usd"), 0.5),
        "min_confidence_delta": _safe_float(config.get("chain_min_confidence_delta"), 0.08),
        "min_evidence_count": 1,
        "min_confidence_floor": 0.35,
        "cost_spent": 0.0,
        "previous_confidence": 0.0,
    }
    policy.update(overrides)
    return policy


def _build_audit_entry(step_result: dict[str, Any], decision: str) -> dict[str, Any]:
    metrics = step_result.get("metrics") if isinstance(step_result.get("metrics"), dict) else {}
    return {
        "step_id": step_result.get("id"),
        "type": step_result.get("type"),
        "inputs": step_result.get("inputs") if isinstance(step_result.get("inputs"), dict) else {},
        "prompt": str(step_result.get("prompt") or ""),
        "model_response": step_result.get("model_response"),
        "metrics": {
            "time": _safe_float(metrics.get("elapsed_sec"), 0.0),
            "tokens": _safe_int(metrics.get("tokens"), 0),
            "cost_est": _safe_float(metrics.get("cost_est"), 0.0),
        },
        "decision": decision,
        "confidence": _safe_float(step_result.get("confidence"), 0.0),
    }


def _execute_single_step(
    step_def: dict[str, Any],
    *,
    context: dict[str, Any],
    config: dict[str, Any],
    depth: int,
) -> dict[str, Any]:
    step_type = str(step_def.get("type") or "").strip()
    if step_type not in STEP_REGISTRY:
        raise ValueError(f"Unsupported chain step type: {step_type}")

    step_id = str(step_def.get("id") or f"{step_type}-{len(context.get('step_results', [])) + 1}")
    params = deepcopy(step_def.get("params")) if isinstance(step_def.get("params"), dict) else {}
    params.setdefault("step_id", step_id)

    func = STEP_REGISTRY[step_type]
    if step_type in {"hypothesis_generation", "targeted_analysis"}:
        result = func(params, context, config)
    else:
        result = func(params, context)

    result["id"] = step_id
    result["type"] = step_type
    result["inputs"] = params
    result["depth"] = depth
    return result


def _run_spawn_actions(
    step_result: dict[str, Any],
    *,
    context: dict[str, Any],
    config: dict[str, Any],
    policy: dict[str, Any],
    audit_trail: list[dict[str, Any]],
    started_at: float,
    branch_state: dict[str, int],
    max_children: int,
) -> None:
    if _safe_int(step_result.get("depth"), 0) >= _safe_int(policy.get("max_depth"), 2):
        return

    actions = step_result.get("spawn_actions") if isinstance(step_result.get("spawn_actions"), list) else []
    if not actions:
        return

    for action in actions[:max_children]:
        if branch_state["count"] >= _safe_int(policy.get("max_branches"), 2):
            break
        if perf_counter() - started_at > _safe_int(policy.get("timeout_sec"), 45):
            break
        if _safe_float(policy.get("cost_spent"), 0.0) >= _safe_float(policy.get("budget_usd"), 0.0):
            break

        if not isinstance(action, dict):
            continue

        child_step = {
            "id": action.get("id") or f"{step_result.get('id')}-branch-{branch_state['count'] + 1}",
            "type": action.get("type"),
            "params": action.get("params") if isinstance(action.get("params"), dict) else {},
        }

        child_result = _execute_single_step(
            child_step,
            context=context,
            config=config,
            depth=_safe_int(step_result.get("depth"), 0) + 1,
        )
        context["step_results"].append(child_result)
        policy["cost_spent"] = _safe_float(policy.get("cost_spent"), 0.0) + _safe_float(
            (child_result.get("metrics") or {}).get("cost_est"), 0.0
        )

        child_continue = should_continue(child_result, policy)
        child_decision = "continue" if child_continue else "stop"
        audit_trail.append(_build_audit_entry(child_result, child_decision))
        branch_state["count"] += 1
        policy["previous_confidence"] = _safe_float(child_result.get("confidence"), 0.0)


def run_chain(chain_def: dict[str, Any], context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    policy = _merge_policy(chain_def, config)
    chain_context = deepcopy(context)
    chain_context.setdefault("step_results", [])

    steps = chain_def.get("steps") if isinstance(chain_def.get("steps"), list) else []
    audit_trail: list[dict[str, Any]] = []
    started_at = perf_counter()
    branch_state = {"count": 0}

    status = "completed"
    conclusion = ""

    for step in steps:
        elapsed = perf_counter() - started_at
        if elapsed > _safe_int(policy.get("timeout_sec"), 45):
            status = "timeout"
            break
        if _safe_float(policy.get("cost_spent"), 0.0) >= _safe_float(policy.get("budget_usd"), 0.0):
            status = "budget_exceeded"
            break

        if isinstance(step, dict) and isinstance(step.get("parallel"), list):
            parallel_steps = [item for item in step.get("parallel", []) if isinstance(item, dict)]
            with ThreadPoolExecutor(max_workers=max(1, len(parallel_steps))) as executor:
                futures = [
                    executor.submit(_execute_single_step, s, context=chain_context, config=config, depth=0)
                    for s in parallel_steps
                ]
                results = [future.result() for future in futures]

            for result in results:
                chain_context["step_results"].append(result)
                policy["cost_spent"] = _safe_float(policy.get("cost_spent"), 0.0) + _safe_float(
                    (result.get("metrics") or {}).get("cost_est"), 0.0
                )
                decision = "continue" if should_continue(result, policy) else "stop"
                audit_trail.append(_build_audit_entry(result, decision))
                policy["previous_confidence"] = _safe_float(result.get("confidence"), 0.0)
                output = result.get("output") if isinstance(result.get("output"), dict) else {}
                if str(output.get("conclusion") or "").strip():
                    conclusion = str(output.get("conclusion"))
                if decision == "stop":
                    status = "stopped"

                branching = step.get("branching") if isinstance(step.get("branching"), dict) else {}
                if bool(branching.get("use_spawn_actions", True)):
                    _run_spawn_actions(
                        result,
                        context=chain_context,
                        config=config,
                        policy=policy,
                        audit_trail=audit_trail,
                        started_at=started_at,
                        branch_state=branch_state,
                        max_children=_safe_int(branching.get("max_children"), _safe_int(policy.get("max_branches"), 2)),
                    )

            if status in {"timeout", "budget_exceeded", "stopped"}:
                break
            continue

        if not isinstance(step, dict):
            continue

        result = _execute_single_step(step, context=chain_context, config=config, depth=0)
        chain_context["step_results"].append(result)

        step_cost = _safe_float((result.get("metrics") or {}).get("cost_est"), 0.0)
        policy["cost_spent"] = _safe_float(policy.get("cost_spent"), 0.0) + step_cost

        can_continue = should_continue(result, policy)
        decision = "continue" if can_continue else "stop"
        audit_trail.append(_build_audit_entry(result, decision))

        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        if str(output.get("conclusion") or "").strip():
            conclusion = str(output.get("conclusion"))

        branching = step.get("branching") if isinstance(step.get("branching"), dict) else {}
        if bool(branching.get("use_spawn_actions", True)):
            _run_spawn_actions(
                result,
                context=chain_context,
                config=config,
                policy=policy,
                audit_trail=audit_trail,
                started_at=started_at,
                branch_state=branch_state,
                max_children=_safe_int(branching.get("max_children"), _safe_int(policy.get("max_branches"), 2)),
            )

        policy["previous_confidence"] = _safe_float(result.get("confidence"), 0.0)

        if not can_continue:
            status = "stopped"
            break

    if not conclusion and chain_context.get("step_results"):
        last = chain_context["step_results"][-1]
        output = last.get("output") if isinstance(last.get("output"), dict) else {}
        conclusion = (
            str(output.get("conclusion") or "").strip()
            or str(output.get("rationale") or "").strip()
            or "Chain executed without a single dominant conclusion."
        )

    final_confidence = _safe_float(
        chain_context.get("step_results", [{}])[-1].get("confidence") if chain_context.get("step_results") else 0.0,
        0.0,
    )
    total_steps = len(chain_context.get("step_results", []))
    elapsed_total = round(perf_counter() - started_at, 4)

    result = {
        "status": status,
        "conclusion": conclusion,
        "audit_trail": audit_trail,
        "cost_estimate": round(_safe_float(policy.get("cost_spent"), 0.0), 6),
        "summary": {
            "steps_count": total_steps,
            "final_confidence": final_confidence,
            "elapsed_sec": elapsed_total,
            "branches_used": branch_state["count"],
        },
    }
    log(
        "Chain completed "
        f"(status={status}, steps={total_steps}, cost_est={result['cost_estimate']:.6f}, confidence={final_confidence:.2f})"
    )
    return result
