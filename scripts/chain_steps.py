#!/usr/bin/env python3
"""Reusable step implementations for follow-up investigative chains."""

from __future__ import annotations

import json
from statistics import mean
from time import perf_counter
from typing import Any

import requests


def _safe_float(value: Any, default: float = 0.0) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _extract_json_payload(raw: str) -> dict[str, Any]:
	raw = str(raw or "").strip()
	if not raw:
		return {}
	try:
		loaded = json.loads(raw)
		return loaded if isinstance(loaded, dict) else {}
	except json.JSONDecodeError:
		return {}


def _extract_opportunities(context: dict[str, Any]) -> list[dict[str, Any]]:
	current = context.get("current_analysis") if isinstance(context.get("current_analysis"), dict) else {}
	ranked = current.get("ranked_opportunities") if isinstance(current.get("ranked_opportunities"), list) else []
	return [item for item in ranked if isinstance(item, dict)]


def _estimate_cost(tokens_total: int, config: dict[str, Any]) -> float:
	rate_per_1k = _safe_float(config.get("chain_cost_per_1k_tokens"), 0.001)
	return round((tokens_total / 1000.0) * rate_per_1k, 6)


def _call_llm_json(prompt: str, config: dict[str, Any], *, deterministic: bool = True) -> dict[str, Any]:
	provider = str(config.get("provider") or "openai").strip().lower()
	model = str(
		config.get("deterministic_model")
		or config.get("followup_model")
		or config.get("model")
		or "gpt-4.1-mini"
	).strip()
	timeout_seconds = int(config.get("timeout_seconds") or 60)

	if provider == "mock":
		payload = {
			"analysis": "Mock chain step analysis generated.",
			"hypotheses": [
				"Recent partner mix shifted away from historically dominant themes.",
				"Opportunity scoring changed due to lower quality inbound demand.",
				"A short-term seasonal effect is suppressing current run scores.",
			],
			"recommended_next_steps": [
				"Review partner-level score deltas for the last three runs.",
				"Validate any scoring rubric changes introduced recently.",
			],
			"confidence": 0.62,
		}
		return {
			"payload": payload,
			"raw": json.dumps(payload, ensure_ascii=False),
			"tokens": 0,
			"cost_est": 0.0,
			"model": model,
		}

	if provider == "azure":
		endpoint = str(config.get("azure_endpoint") or "").strip().rstrip("/")
		deployment = str(
			config.get("azure_deployment") or config.get("followup_model") or config.get("model") or ""
		).strip()
		api_key = str(config.get("azure_api_key") or config.get("api_key") or "").strip()
		api_version = str(config.get("azure_api_version") or "2024-06-01").strip()
		if not endpoint or not deployment or not api_key:
			raise ValueError("Azure chain step config requires endpoint, deployment, and api key")
		url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
		headers = {"api-key": api_key, "Content-Type": "application/json"}
		body = {
			"temperature": 0 if deterministic else 0.2,
			"seed": 0,
			"response_format": {"type": "json_object"},
			"messages": [{"role": "user", "content": prompt}],
		}
	else:
		api_key = str(config.get("api_key") or "").strip()
		if not api_key:
			raise ValueError("Missing OpenAI API key for chain steps")
		url = "https://api.openai.com/v1/chat/completions"
		headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
		body = {
			"model": model,
			"temperature": 0 if deterministic else 0.2,
			"seed": 0,
			"response_format": {"type": "json_object"},
			"messages": [{"role": "user", "content": prompt}],
		}

	response = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
	response.raise_for_status()
	data = response.json()
	raw = data.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
	usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
	prompt_tokens = int(usage.get("prompt_tokens") or 0)
	completion_tokens = int(usage.get("completion_tokens") or 0)
	total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
	return {
		"payload": _extract_json_payload(str(raw)),
		"raw": str(raw),
		"tokens": total_tokens,
		"cost_est": _estimate_cost(total_tokens, config),
		"model": model,
	}


def _result(
	*,
	step_id: str,
	step_type: str,
	output: dict[str, Any],
	confidence: float,
	continue_flag: bool,
	spawn_actions: list[dict[str, Any]],
	prompt: str = "",
	model_response: Any = "",
	metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
	return {
		"id": step_id,
		"type": step_type,
		"output": output,
		"confidence": max(0.0, min(1.0, _safe_float(confidence))),
		"continue_flag": bool(continue_flag),
		"spawn_actions": spawn_actions,
		"prompt": prompt,
		"model_response": model_response,
		"metrics": metrics or {},
	}


def compare_runs_step(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
	started = perf_counter()
	step_id = str(params.get("step_id") or "compare-runs")
	history = context.get("analysis_history") if isinstance(context.get("analysis_history"), list) else []
	current = context.get("current_analysis") if isinstance(context.get("current_analysis"), dict) else {}

	lookback = max(2, int(params.get("lookback") or 3))
	recent = [item for item in history if isinstance(item, dict)][-max(0, lookback - 1) :]
	recent.append(current)
	recent = [item for item in recent if isinstance(item, dict)]

	run_metrics: list[dict[str, Any]] = []
	for run in recent:
		ranked = run.get("ranked_opportunities") if isinstance(run.get("ranked_opportunities"), list) else []
		scores = [_safe_float(item.get("score")) for item in ranked if isinstance(item, dict)]
		run_metrics.append(
			{
				"run_id": run.get("run_id"),
				"opportunity_count": len(scores),
				"avg_score": round(mean(scores), 4) if scores else 0.0,
			}
		)

	deltas: dict[str, Any] = {}
	if len(run_metrics) >= 2:
		prev = run_metrics[-2]
		now = run_metrics[-1]
		deltas = {
			"opportunity_count": int(now.get("opportunity_count", 0)) - int(prev.get("opportunity_count", 0)),
			"avg_score": round(_safe_float(now.get("avg_score")) - _safe_float(prev.get("avg_score")), 4),
		}

	confidence = 0.65 if run_metrics else 0.2
	elapsed = round(perf_counter() - started, 4)
	return _result(
		step_id=step_id,
		step_type="compare_runs",
		output={"lookback": lookback, "runs": run_metrics, "deltas": deltas},
		confidence=confidence,
		continue_flag=bool(run_metrics),
		spawn_actions=[],
		metrics={"elapsed_sec": elapsed, "tokens": 0, "cost_est": 0.0},
	)


def extract_evidence_step(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
	started = perf_counter()
	step_id = str(params.get("step_id") or "extract-evidence")
	top_n = max(1, int(params.get("top_n") or 5))

	opportunities = _extract_opportunities(context)
	opportunities.sort(key=lambda item: _safe_float(item.get("score"), 0.0), reverse=True)

	evidence = []
	for item in opportunities[:top_n]:
		evidence.append(
			{
				"title": item.get("title") or item.get("name") or "Untitled",
				"score": round(_safe_float(item.get("score"), 0.0), 4),
				"theme": item.get("theme") or item.get("cluster_label") or item.get("category") or "Uncategorized",
				"partner": item.get("partner") or item.get("partner_name") or "Unspecified",
				"summary": str(item.get("summary") or "").strip(),
			}
		)

	confidence = min(0.95, 0.45 + (0.07 * len(evidence)))
	elapsed = round(perf_counter() - started, 4)
	return _result(
		step_id=step_id,
		step_type="extract_evidence",
		output={"top_n": top_n, "evidence": evidence, "evidence_count": len(evidence)},
		confidence=confidence,
		continue_flag=bool(evidence),
		spawn_actions=[],
		metrics={"elapsed_sec": elapsed, "tokens": 0, "cost_est": 0.0},
	)


def hypothesis_generation_step(params: dict[str, Any], context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
	started = perf_counter()
	step_id = str(params.get("step_id") or "hypothesis-generation")
	top_k = max(1, int(params.get("top_k") or 3))
	spawn_top_n = max(0, int(params.get("spawn_top_n") or 2))

	prior_evidence = []
	for step in context.get("step_results", []):
		if not isinstance(step, dict):
			continue
		output = step.get("output") if isinstance(step.get("output"), dict) else {}
		if isinstance(output.get("evidence"), list):
			prior_evidence.extend(output.get("evidence"))
	prior_evidence = [item for item in prior_evidence if isinstance(item, dict)][:8]

	prompt = (
		"You are an investigative analyst. Return JSON with keys: hypotheses (array of strings), "
		"confidence (0..1), rationale (string).\n"
		"Generate concise root-cause hypotheses grounded in this evidence:\n"
		f"{json.dumps(prior_evidence, ensure_ascii=False)}\n"
		f"Limit hypotheses to top {top_k}."
	)

	response = _call_llm_json(prompt, config, deterministic=True)
	payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
	raw_hypotheses = payload.get("hypotheses") if isinstance(payload.get("hypotheses"), list) else []
	hypotheses = [str(item).strip() for item in raw_hypotheses if str(item).strip()][:top_k]
	model_conf = _safe_float(payload.get("confidence"), 0.0)
	confidence = model_conf if model_conf > 0 else (0.55 if hypotheses else 0.2)

	spawn_actions: list[dict[str, Any]] = []
	for hypothesis in hypotheses[:spawn_top_n]:
		spawn_actions.append(
			{
				"type": "validate_hypothesis",
				"params": {"hypothesis": hypothesis},
			}
		)

	elapsed = round(perf_counter() - started, 4)
	return _result(
		step_id=step_id,
		step_type="hypothesis_generation",
		output={
			"hypotheses": hypotheses,
			"rationale": str(payload.get("rationale") or "").strip(),
			"evidence_count": len(prior_evidence),
		},
		confidence=confidence,
		continue_flag=bool(hypotheses),
		spawn_actions=spawn_actions,
		prompt=prompt,
		model_response=response.get("raw") or "",
		metrics={
			"elapsed_sec": elapsed,
			"tokens": int(response.get("tokens") or 0),
			"cost_est": _safe_float(response.get("cost_est"), 0.0),
			"model": str(response.get("model") or ""),
		},
	)


def validate_hypothesis_step(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
	started = perf_counter()
	hypothesis = str(params.get("hypothesis") or "").strip()
	step_id = str(params.get("step_id") or f"validate-{len(context.get('step_results', [])) + 1}")

	evidence = []
	opportunities = _extract_opportunities(context)
	hypothesis_terms = [term.lower() for term in hypothesis.split() if len(term) > 3]

	support_examples: list[dict[str, Any]] = []
	for item in opportunities:
		text_blob = " ".join(
			[
				str(item.get("title") or ""),
				str(item.get("summary") or ""),
				str(item.get("theme") or item.get("cluster_label") or ""),
				str(item.get("partner") or item.get("partner_name") or ""),
			]
		).lower()
		if any(term in text_blob for term in hypothesis_terms):
			support_examples.append(
				{
					"title": item.get("title") or item.get("name") or "Untitled",
					"score": round(_safe_float(item.get("score"), 0.0), 4),
					"summary": str(item.get("summary") or "").strip(),
				}
			)
		if len(support_examples) >= 5:
			break

	support_count = len(support_examples)
	total = max(1, len(opportunities))
	support_ratio = support_count / total
	confidence = min(0.95, 0.35 + (support_ratio * 1.3))
	verdict = "supported" if support_count >= 2 else "weak"

	evidence.append(f"Support examples found: {support_count} out of {total} opportunities")
	elapsed = round(perf_counter() - started, 4)
	return _result(
		step_id=step_id,
		step_type="validate_hypothesis",
		output={
			"hypothesis": hypothesis,
			"verdict": verdict,
			"support_count": support_count,
			"sample_examples": support_examples,
			"evidence": evidence,
		},
		confidence=confidence,
		continue_flag=support_count > 0,
		spawn_actions=[],
		metrics={"elapsed_sec": elapsed, "tokens": 0, "cost_est": 0.0},
	)


def targeted_analysis_step(params: dict[str, Any], context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
	started = perf_counter()
	step_id = str(params.get("step_id") or "targeted-analysis")
	objective = str(params.get("objective") or "Provide focused analysis and next steps.")

	evidence_items = []
	for step in context.get("step_results", []):
		if not isinstance(step, dict):
			continue
		output = step.get("output") if isinstance(step.get("output"), dict) else {}
		if isinstance(output.get("evidence"), list):
			evidence_items.extend(output.get("evidence"))
	evidence_items = evidence_items[:10]

	prompt = (
		"You are performing a focused, deterministic analysis. Return JSON keys: conclusion (string), "
		"recommended_next_steps (array of strings), confidence (0..1).\n"
		f"Objective: {objective}\n"
		f"Evidence: {json.dumps(evidence_items, ensure_ascii=False)}"
	)
	response = _call_llm_json(prompt, config, deterministic=True)
	payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}

	next_steps = payload.get("recommended_next_steps") if isinstance(payload.get("recommended_next_steps"), list) else []
	clean_next_steps = [str(item).strip() for item in next_steps if str(item).strip()][:5]
	conclusion = str(payload.get("conclusion") or payload.get("analysis") or "").strip()
	confidence = _safe_float(payload.get("confidence"), 0.55 if conclusion else 0.2)

	elapsed = round(perf_counter() - started, 4)
	return _result(
		step_id=step_id,
		step_type="targeted_analysis",
		output={"conclusion": conclusion, "recommended_next_steps": clean_next_steps},
		confidence=confidence,
		continue_flag=bool(conclusion),
		spawn_actions=[],
		prompt=prompt,
		model_response=response.get("raw") or "",
		metrics={
			"elapsed_sec": elapsed,
			"tokens": int(response.get("tokens") or 0),
			"cost_est": _safe_float(response.get("cost_est"), 0.0),
			"model": str(response.get("model") or ""),
		},
	)


STEP_REGISTRY = {
	"compare_runs": compare_runs_step,
	"extract_evidence": extract_evidence_step,
	"hypothesis_generation": hypothesis_generation_step,
	"validate_hypothesis": validate_hypothesis_step,
	"targeted_analysis": targeted_analysis_step,
}

