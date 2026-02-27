#!/usr/bin/env python3
"""Agent-driven follow-up investigation helpers for high-severity alerts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from log_utils import log
from output_writer import write_json


FOLLOWUP_SCHEMA_KEYS = [
    "deeper_analysis",
    "root_causes",
    "supporting_evidence",
    "recommended_next_steps",
    "confidence",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_preview(value: Any, max_chars: int = 1200) -> str:
    rendered = json.dumps(value, ensure_ascii=False)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max_chars - 3] + "..."


def _history_preview(analysis_history: list[dict[str, Any]], max_runs: int = 3) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for run in analysis_history[-max_runs:]:
        if not isinstance(run, dict):
            continue
        previews.append(
            {
                "run_id": run.get("run_id"),
                "generated_utc": run.get("generated_utc"),
                "sheet_summary": run.get("sheet_summary"),
                "top_tags": run.get("top_tags") if isinstance(run.get("top_tags"), list) else [],
                "counts_by_status": (
                    run.get("counts_by_status") if isinstance(run.get("counts_by_status"), dict) else {}
                ),
                "top_opportunities": [
                    {
                        "title": item.get("title") or item.get("name"),
                        "score": item.get("score"),
                        "theme": item.get("theme") or item.get("cluster_label"),
                        "partner": item.get("partner") or item.get("partner_name"),
                    }
                    for item in (
                        run.get("ranked_opportunities")
                        if isinstance(run.get("ranked_opportunities"), list)
                        else []
                    )[:3]
                    if isinstance(item, dict)
                ],
            }
        )
    return previews


def _targeted_instructions(alert_type: str) -> str:
    instructions = {
        "emergence": "Focus on what newly appeared, possible triggering events, and whether this is likely durable versus transient.",
        "decline": "Focus on what declined, potential displacement factors, and whether the decline indicates risk, saturation, or re-prioritization.",
        "anomaly": "Focus on outlier behavior, data-quality checks, and plausible operational or market explanations.",
        "divergence": "Focus on why segments/partners/themes are moving differently and what structural differences might explain separation.",
        "concentration": "Focus on concentration risk, dependency exposure, and whether distribution should be diversified.",
    }
    return instructions.get(
        alert_type,
        "Focus on likely causes, practical implications, and concrete next investigative steps.",
    )


def generate_followup_prompt(alert: dict[str, Any], analysis_history: list[dict[str, Any]]) -> str:
    alert_type = str(alert.get("type") or "anomaly").strip().lower()
    evidence = alert.get("evidence") if isinstance(alert.get("evidence"), list) else []
    history_context = _history_preview(analysis_history, max_runs=3)

    request_payload = {
        "alert": {
            "id": alert.get("id"),
            "type": alert_type,
            "severity": alert.get("severity"),
            "title": alert.get("title"),
            "summary": alert.get("summary"),
            "confidence": alert.get("confidence"),
            "evidence": evidence,
        },
        "historical_context": history_context,
    }

    return (
        "You are an investigative analysis agent. Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "deeper_analysis": "string",\n'
        '  "root_causes": ["string", "..."],\n'
        '  "supporting_evidence": ["string", "..."],\n'
        '  "recommended_next_steps": ["string", "..."],\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "Constraints:\n"
        "- Keep analysis grounded in provided evidence and historical context.\n"
        "- Provide 3-6 root-cause hypotheses with uncertainty-aware wording.\n"
        "- Provide 3-6 supporting evidence statements tied to signal patterns.\n"
        "- Provide 3-6 recommended next questions/steps for follow-up investigation.\n"
        "- Confidence must be a number between 0 and 1.\n"
        "- No markdown, no code fences, no additional keys.\n\n"
        f"Targeted objective for alert type '{alert_type}': {_targeted_instructions(alert_type)}\n\n"
        "Investigation input:\n"
        f"{_json_preview(request_payload, max_chars=6000)}\n"
    )


def _extract_json_payload(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        raise RuntimeError("AI response content was empty")

    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        loaded = json.loads(fenced.group(1))
        if isinstance(loaded, dict):
            return loaded

    raise RuntimeError("AI response was not a valid JSON object")


def _normalize_followup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "deeper_analysis": str(payload.get("deeper_analysis") or "").strip(),
        "root_causes": [str(item).strip() for item in payload.get("root_causes", []) if str(item).strip()]
        if isinstance(payload.get("root_causes"), list)
        else [],
        "supporting_evidence": [
            str(item).strip() for item in payload.get("supporting_evidence", []) if str(item).strip()
        ]
        if isinstance(payload.get("supporting_evidence"), list)
        else [],
        "recommended_next_steps": [
            str(item).strip() for item in payload.get("recommended_next_steps", []) if str(item).strip()
        ]
        if isinstance(payload.get("recommended_next_steps"), list)
        else [],
        "confidence": max(0.0, min(1.0, _safe_float(payload.get("confidence"), 0.0))),
    }

    for key in FOLLOWUP_SCHEMA_KEYS:
        normalized.setdefault(key, [] if key.endswith("s") else "")
    return normalized


def _call_openai(prompt: str, config: dict[str, Any]) -> str:
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("Missing OpenAI API key")

    model = str(config.get("followup_model") or config.get("model") or "gpt-4o-mini").strip()
    timeout_seconds = int(config.get("timeout_seconds") or 60)

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI follow-up response content was empty")
    return content


def _call_azure_openai(prompt: str, config: dict[str, Any]) -> str:
    endpoint = str(
        config.get("azure_endpoint")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or ""
    ).strip()
    api_key = str(
        config.get("azure_api_key")
        or config.get("api_key")
        or os.environ.get("AZURE_OPENAI_API_KEY")
        or ""
    ).strip()
    deployment = str(
        config.get("azure_deployment")
        or config.get("followup_model")
        or config.get("model")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()
    api_version = str(
        config.get("azure_api_version")
        or os.environ.get("AZURE_OPENAI_API_VERSION")
        or "2024-06-01"
    ).strip()
    timeout_seconds = int(config.get("timeout_seconds") or 60)

    if not endpoint or not api_key or not deployment:
        raise ValueError("Azure follow-up config requires endpoint, api_key, and deployment")

    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    response = requests.post(
        url,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Azure OpenAI follow-up response content was empty")
    return content


def run_followup_agent(prompt: str, config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config.get("provider") or "openai").strip().lower()

    if provider == "mock":
        return {
            "deeper_analysis": "Mock follow-up generated for local validation.",
            "root_causes": [
                "Short-term concentration in recent opportunity inflow.",
                "Recent partner demand shift relative to historical baseline.",
            ],
            "supporting_evidence": [
                "Alert evidence indicates a large week-over-week change against baseline.",
                "Historical context shows this pattern is atypical across recent runs.",
            ],
            "recommended_next_steps": [
                "Validate source data integrity for the affected segments.",
                "Interview owners for the top impacted partner/theme combinations.",
                "Track this signal for two additional runs before policy changes.",
            ],
            "confidence": 0.66,
        }

    try:
        if provider == "azure":
            raw = _call_azure_openai(prompt, config)
        else:
            raw = _call_openai(prompt, config)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        body = (exc.response.text or "")[:300] if exc.response is not None else ""
        raise RuntimeError(f"Follow-up agent HTTP error (status {status}): {body}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Follow-up agent request failed: {exc}") from exc

    payload = _extract_json_payload(raw)
    return _normalize_followup_payload(payload)


def _to_markdown_list(items: list[str], empty_message: str) -> list[str]:
    if not items:
        return [f"- {empty_message}"]
    return [f"- {item}" for item in items]


def _sanitize_for_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-") or "alert"


def write_followup_output(run_id: str, alert_id: str, followup: dict[str, Any], output_dir: str) -> dict[str, str]:
    sanitized_alert_id = _sanitize_for_filename(alert_id)
    file_stem = f"followup-{run_id}-{sanitized_alert_id}"

    analysis_path = Path(output_dir) / f"{file_stem}.json"
    docs_path = Path("docs") / f"{file_stem}.md"

    write_json(str(analysis_path), followup)

    deeper_analysis = str(followup.get("deeper_analysis") or "").strip()
    confidence = _safe_float(followup.get("confidence"), 0.0)
    root_causes = followup.get("root_causes") if isinstance(followup.get("root_causes"), list) else []
    supporting_evidence = (
        followup.get("supporting_evidence") if isinstance(followup.get("supporting_evidence"), list) else []
    )
    next_steps = (
        followup.get("recommended_next_steps")
        if isinstance(followup.get("recommended_next_steps"), list)
        else []
    )

    markdown_lines = [
        f"# Follow-Up Investigation — {alert_id}",
        "",
        f"Run ID: {run_id}",
        f"Confidence: {confidence:.2f}",
        "",
        "## Deeper Analysis",
        "",
        deeper_analysis or "No deeper analysis generated.",
        "",
        "## Root-Cause Hypotheses",
        "",
        *_to_markdown_list([str(item) for item in root_causes], "No hypotheses generated."),
        "",
        "## Supporting Evidence",
        "",
        *_to_markdown_list([str(item) for item in supporting_evidence], "No supporting evidence generated."),
        "",
        "## Recommended Next Steps",
        "",
        *_to_markdown_list([str(item) for item in next_steps], "No next steps generated."),
        "",
    ]

    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    log(f"Wrote follow-up JSON to {analysis_path}")
    log(f"Wrote follow-up markdown to {docs_path}")

    return {
        "analysis_json": str(analysis_path),
        "docs_markdown": str(docs_path),
    }
