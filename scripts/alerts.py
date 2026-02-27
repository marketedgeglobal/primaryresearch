#!/usr/bin/env python3
"""Automated alert generation and remediation playbook rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from followups import generate_followup_prompt, run_followup_agent, write_followup_output
from log_utils import log
from output_writer import write_json


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_scalar(value: str) -> Any:
    raw = value.strip()
    if not raw:
        return ""
    if (raw.startswith("\"") and raw.endswith("\"")) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]

    lowered = raw.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False

    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def load_playbooks(path: str | Path) -> dict[str, Any]:
    playbook_path = Path(path)
    if not playbook_path.exists():
        log(f"Playbooks file not found: {playbook_path}")
        return {}

    return _parse_playbooks_yaml(playbook_path.read_text(encoding="utf-8"))


def _parse_playbooks_yaml(raw: str) -> dict[str, Any]:
    playbooks: dict[str, Any] = {}
    current_type: str | None = None
    current_section: str | None = None
    current_action: dict[str, Any] | None = None
    notes_lines: list[str] = []

    def _flush_notes() -> None:
        nonlocal notes_lines
        if current_type and notes_lines:
            playbooks[current_type]["notes"] = " ".join(part.strip() for part in notes_lines if part.strip())
            notes_lines = []

    for raw_line in raw.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if indent == 0 and stripped.endswith(":"):
            _flush_notes()
            current_type = stripped[:-1].strip()
            playbooks[current_type] = {
                "severity_threshold": {"high": 0.8, "medium": 0.6},
                "actions": [],
                "notes": "",
            }
            current_section = None
            current_action = None
            continue

        if current_type is None:
            continue

        if indent == 2 and stripped.endswith(":"):
            _flush_notes()
            current_section = stripped[:-1].strip()
            current_action = None
            continue

        if indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "notes":
                current_section = "notes"
                if value and value not in {"|", ">", "|-", ">-"}:
                    playbooks[current_type]["notes"] = str(_clean_scalar(value))
                    current_section = None
                else:
                    notes_lines = []
            else:
                playbooks[current_type][key] = _clean_scalar(value)
            continue

        if current_section == "severity_threshold" and indent >= 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            playbooks[current_type]["severity_threshold"][key.strip()] = _safe_float(_clean_scalar(value), 0.0)
            continue

        if current_section == "actions":
            if indent == 4 and stripped.startswith("- "):
                action_line = stripped[2:].strip()
                action_obj: dict[str, Any] = {}
                if action_line and ":" in action_line:
                    key, value = action_line.split(":", 1)
                    action_obj[key.strip()] = _clean_scalar(value)
                elif action_line:
                    action_obj["action"] = _clean_scalar(action_line)
                playbooks[current_type]["actions"].append(action_obj)
                current_action = action_obj
                continue

            if indent >= 6 and ":" in stripped and current_action is not None:
                key, value = stripped.split(":", 1)
                current_action[key.strip()] = _clean_scalar(value)
                continue

        if current_section == "notes" and indent >= 4:
            notes_lines.append(stripped)

    _flush_notes()
    return playbooks


def _severity_score(insight: dict[str, Any]) -> float:
    confidence = _safe_float(insight.get("confidence"), 0.0)
    evidence = insight.get("evidence") if isinstance(insight.get("evidence"), list) else []

    signal_values: list[float] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        for key in ("delta", "delta_count", "previous_count", "current_count", "count", "total_count"):
            if key in item:
                signal_values.append(abs(_safe_float(item.get(key), 0.0)))
        if "score_spread" in item:
            signal_values.append(_safe_float(item.get("score_spread"), 0.0) * 10.0)
        if "share" in item:
            signal_values.append(_safe_float(item.get("share"), 0.0) * 10.0)
        if "delta_average_score" in item:
            signal_values.append(abs(_safe_float(item.get("delta_average_score"), 0.0)) * 10.0)

    if not signal_values:
        return confidence

    max_signal = max(signal_values)
    normalized_signal = min(1.0, max_signal / 10.0)
    return max(confidence, normalized_signal)


def _determine_severity(score: float, thresholds: dict[str, Any], defaults: dict[str, Any]) -> str:
    high_threshold = _safe_float(
        thresholds.get("high", defaults.get("high_severity_threshold", 0.8)),
        0.8,
    )
    medium_threshold = _safe_float(
        thresholds.get("medium", defaults.get("medium_severity_threshold", 0.6)),
        0.6,
    )

    if score >= high_threshold:
        return "high"
    if score >= medium_threshold:
        return "medium"
    return "low"


def _recommended_actions(playbook: dict[str, Any], fallback_type: str) -> list[dict[str, Any]]:
    raw_actions = playbook.get("actions") if isinstance(playbook.get("actions"), list) else []
    actions: list[dict[str, Any]] = []

    for index, action in enumerate(raw_actions, start=1):
        if isinstance(action, dict):
            title = str(action.get("title") or action.get("action") or f"Action {index}")
            owner = str(action.get("owner") or action.get("role") or "Team lead")
            timeline = str(action.get("timeline") or action.get("timeframe") or "This week")
            detail = str(action.get("detail") or action.get("description") or "")
            actions.append(
                {
                    "title": title,
                    "owner": owner,
                    "timeline": timeline,
                    "detail": detail,
                }
            )
        elif isinstance(action, str):
            actions.append(
                {
                    "title": action,
                    "owner": "Team lead",
                    "timeline": "This week",
                    "detail": "",
                }
            )

    if actions:
        return actions

    return [
        {
            "title": f"Review {fallback_type} insight with owners",
            "owner": "Research lead",
            "timeline": "24-48h",
            "detail": "Confirm impact, assign accountable owner, and define next check-in.",
        }
    ]


def load_recent_analysis_history(analyses_dir: str | Path, current_run_id: str, max_runs: int = 3) -> list[dict[str, Any]]:
    directory = Path(analyses_dir)
    if not directory.exists():
        return []

    candidates = sorted(directory.glob("weekly-*.json"), key=lambda path: path.stat().st_mtime)
    history: list[dict[str, Any]] = []

    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        run_id = str(payload.get("run_id") or "")
        if run_id and run_id == current_run_id:
            continue
        history.append(payload)

    return history[-max_runs:]


def _generate_high_severity_followups(
    alerts: list[dict[str, Any]],
    *,
    run_id: str,
    config: dict[str, Any],
) -> None:
    if not alerts:
        return

    analysis_history = config.get("analysis_history") if isinstance(config.get("analysis_history"), list) else []
    output_dir = str(config.get("output_dir") or "analyses")

    high_alerts = [item for item in alerts if str(item.get("severity")) == "high"]
    if not high_alerts:
        return

    for alert in high_alerts:
        alert_run_id = str(alert.get("run_id") or run_id)
        alert_id = str(alert.get("id") or "alert")

        try:
            prompt = generate_followup_prompt(alert, analysis_history)
            followup_payload = run_followup_agent(prompt, config)
            output_paths = write_followup_output(alert_run_id, alert_id, followup_payload, output_dir)
            alert["followup_path"] = output_paths["docs_markdown"]
        except Exception as exc:
            log(f"Follow-up generation failed for alert {alert_id}: {exc}")
            alert["followup_path"] = ""


def generate_alerts(insights: list[dict[str, Any]], playbooks: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(config.get("run_id") or "")
    alerts: list[dict[str, Any]] = []

    for index, insight in enumerate(insights, start=1):
        if not isinstance(insight, dict):
            continue

        insight_type = str(insight.get("type") or "anomaly")
        playbook = playbooks.get(insight_type) if isinstance(playbooks.get(insight_type), dict) else {}
        thresholds = playbook.get("severity_threshold") if isinstance(playbook.get("severity_threshold"), dict) else {}

        score = _severity_score(insight)
        severity = _determine_severity(score, thresholds, config)

        insight_run_ids = insight.get("run_ids") if isinstance(insight.get("run_ids"), list) else []
        resolved_run_id = run_id or (str(insight_run_ids[-1]) if insight_run_ids else "")

        title = str(insight.get("title") or insight.get("narrative") or f"Automated alert {index}")
        summary = str(insight.get("narrative") or title)
        evidence = insight.get("evidence") if isinstance(insight.get("evidence"), list) else []
        confidence = round(_safe_float(insight.get("confidence"), 0.0), 2)
        source_id = str(insight.get("id") or f"{insight_type}-{index}")

        alerts.append(
            {
                "id": f"alert-{source_id}",
                "type": insight_type,
                "severity": severity,
                "title": title,
                "summary": summary,
                "evidence": evidence,
                "recommended_actions": _recommended_actions(playbook, insight_type),
                "confidence": confidence,
                "run_id": resolved_run_id,
                "followup_path": "",
            }
        )

    alerts.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity")), 99),
            -_safe_float(item.get("confidence"), 0.0),
        )
    )

    _generate_high_severity_followups(
        alerts,
        run_id=run_id,
        config=config,
    )

    return alerts


def _render_evidence_table(evidence: list[dict[str, Any]]) -> list[str]:
    lines = ["| Metric | Value |", "| --- | --- |"]
    row_count = 0

    for item in evidence:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key == "opportunities":
                continue
            rendered = value
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False)
            lines.append(f"| {key.replace('_', ' ').title()} | {rendered} |")
            row_count += 1

    if row_count == 0:
        lines.append("| Evidence | No structured evidence provided |")

    return lines


def _render_alert_group(alerts: list[dict[str, Any]], heading: str) -> list[str]:
    lines: list[str] = [f"## {heading}", ""]
    if not alerts:
        lines.extend(["- None", ""])
        return lines

    for index, alert in enumerate(alerts, start=1):
        title = str(alert.get("title") or f"Alert {index}")
        summary = str(alert.get("summary") or "")
        confidence = _safe_float(alert.get("confidence"), 0.0)
        evidence = alert.get("evidence") if isinstance(alert.get("evidence"), list) else []
        recommended_actions = (
            alert.get("recommended_actions")
            if isinstance(alert.get("recommended_actions"), list)
            else []
        )

        lines.append(f"### {index}. {title}")
        lines.append("")
        lines.append(f"- **Severity:** {alert.get('severity', 'unknown')}")
        lines.append(f"- **Confidence:** {confidence:.2f}")
        lines.append("")

        if summary:
            lines.append(summary)
            lines.append("")

        lines.append("#### Evidence")
        lines.append("")
        lines.extend(_render_evidence_table(evidence))
        lines.append("")

        lines.append("#### Recommended Actions")
        lines.append("")
        for action in recommended_actions:
            if not isinstance(action, dict):
                continue
            title_text = str(action.get("title") or action.get("action") or "Action")
            owner = str(action.get("owner") or "Team")
            timeline = str(action.get("timeline") or "This week")
            detail = str(action.get("detail") or "")
            line = f"- **{title_text}** — Owner: {owner}; Timeline: {timeline}"
            if detail:
                line += f"; Detail: {detail}"
            lines.append(line)
        lines.append("")

    return lines


def render_alerts_markdown(alerts: list[dict[str, Any]], run_metadata: dict[str, Any]) -> str:
    run_id = str(run_metadata.get("run_id") or "")
    generated_utc = str(run_metadata.get("generated_utc") or "")

    high_alerts = [item for item in alerts if str(item.get("severity")) == "high"]
    medium_alerts = [item for item in alerts if str(item.get("severity")) == "medium"]

    lines: list[str] = [f"# Automated Alerts — {run_id}", ""]
    if generated_utc:
        lines.extend([f"Generated UTC: {generated_utc}", ""])

    lines.extend(_render_alert_group(high_alerts, "High Severity Alerts"))
    lines.extend(_render_alert_group(medium_alerts, "Medium Severity Alerts"))

    return "\n".join(lines).rstrip() + "\n"


def write_alerts_output(run_id: str, alerts: list[dict[str, Any]], output_dir: str) -> dict[str, str]:
    analysis_path = Path(output_dir) / f"alerts-{run_id}.json"
    docs_path = Path("docs") / f"alerts-{run_id}.md"

    payload = {
        "run_id": run_id,
        "alerts": alerts,
    }
    write_json(str(analysis_path), payload)

    markdown = render_alerts_markdown(alerts, {"run_id": run_id})
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(markdown, encoding="utf-8")

    log(f"Wrote alerts JSON to {analysis_path}")
    log(f"Wrote alerts markdown to {docs_path}")

    return {
        "analysis_json": str(analysis_path),
        "docs_markdown": str(docs_path),
    }
