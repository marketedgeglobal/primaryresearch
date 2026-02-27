#!/usr/bin/env python3
"""Markdown summary generation helpers for weekly analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from log_utils import log


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_top_insights_section(analysis: dict[str, Any], run_id: str) -> list[str]:
    insights = analysis.get("automated_insights") if isinstance(analysis.get("automated_insights"), list) else []
    if not insights:
        return []

    insights_doc_path = str(analysis.get("insights_doc_path") or f"insights-{run_id}.md")
    lines: list[str] = ["## Top Automated Insights", ""]
    for insight in insights[:3]:
        if not isinstance(insight, dict):
            continue
        narrative = str(insight.get("narrative") or insight.get("title") or "")
        confidence = _safe_float(insight.get("confidence") or 0.0)
        lines.append(f"- {narrative} (confidence: {confidence:.2f})")
    lines.extend(["", f"- Full details: [{insights_doc_path}]({insights_doc_path})", ""])
    return lines


def _build_followups_section(run_id: str, analyses_dir: Path = Path("analyses")) -> list[str]:
    alerts_path = analyses_dir / f"alerts-{run_id}.json"
    if not alerts_path.exists():
        return []

    try:
        payload = json.loads(alerts_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    alerts = payload.get("alerts") if isinstance(payload, dict) else []
    if not isinstance(alerts, list):
        return []

    high_followups = [
        item
        for item in alerts
        if isinstance(item, dict) and str(item.get("severity")) == "high" and str(item.get("followup_path") or "").strip()
    ]
    if not high_followups:
        return []

    high_followups.sort(key=lambda item: _safe_float(item.get("confidence"), 0.0), reverse=True)

    lines = ["## Follow-Up Investigations", ""]
    for alert in high_followups[:2]:
        title = str(alert.get("title") or "Untitled alert")
        confidence = _safe_float(alert.get("confidence"), 0.0)
        followup_doc = Path(str(alert.get("followup_path") or "")).name

        teaser = "Follow-up generated."
        followup_json = analyses_dir / f"{Path(followup_doc).stem}.json"
        if followup_json.exists():
            try:
                followup_payload = json.loads(followup_json.read_text(encoding="utf-8"))
                deeper = str(followup_payload.get("deeper_analysis") or "").strip()
                if deeper:
                    teaser = deeper[:180] + ("..." if len(deeper) > 180 else "")
            except Exception:
                teaser = "Follow-up generated."

        lines.append(f"- **{title}** (alert confidence: {confidence:.2f})")
        lines.append(f"  - {teaser}")
        lines.append(f"  - Full follow-up: [{followup_doc}]({followup_doc})")

    lines.append("")
    return lines


def build_markdown_summary(analysis: dict[str, Any], run_id: str) -> str:
    generated_utc = str(analysis.get("generated_utc") or "")
    sheet_summary = str(analysis.get("sheet_summary") or "No summary available.")
    top_tags = analysis.get("top_tags") if isinstance(analysis.get("top_tags"), list) else []
    counts_by_status = analysis.get("counts_by_status") if isinstance(analysis.get("counts_by_status"), dict) else {}
    deadline_overview = analysis.get("deadline_overview") if isinstance(analysis.get("deadline_overview"), dict) else {}
    ranked_opportunities = (
        analysis.get("ranked_opportunities") if isinstance(analysis.get("ranked_opportunities"), list) else []
    )
    clusters = analysis.get("clusters") if isinstance(analysis.get("clusters"), list) else []

    lines: list[str] = [f"# Weekly Analysis Summary — {run_id}", ""]
    if generated_utc:
        lines.extend([f"Generated UTC: {generated_utc}", ""])

    lines.extend(["## Overview", "", sheet_summary, ""])

    lines.extend(_build_top_insights_section(analysis, run_id))
    lines.extend(_build_followups_section(run_id))

    if top_tags:
        lines.append("## Top Tags")
        lines.append("")
        for tag in top_tags:
            lines.append(f"- {tag}")
        lines.append("")

    if counts_by_status:
        lines.append("## Status Counts")
        lines.append("")
        for status, count in counts_by_status.items():
            lines.append(f"- {status}: {count}")
        lines.append("")

    if deadline_overview:
        lines.append("## Deadline Overview")
        lines.append("")
        for key, value in deadline_overview.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    if ranked_opportunities:
        lines.append("## Top Opportunities")
        lines.append("")
        top_n = max(3, min(5, len(ranked_opportunities)))
        for opportunity in ranked_opportunities[:top_n]:
            if not isinstance(opportunity, dict):
                continue
            title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
            summary = str(opportunity.get("summary") or "")
            score = float(opportunity.get("score") or 0.0)
            lines.append(f"- **{title}** (score: {score:.2f})")
            if summary:
                lines.append(f"  - {summary}")
        lines.append("")

    if clusters:
        lines.append("## Top Themes")
        lines.append("")
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            label = str(cluster.get("label") or f"Cluster {cluster.get('id', '?')}")
            lines.append(f"- **{label}**")
            opportunities = cluster.get("opportunities") if isinstance(cluster.get("opportunities"), list) else []
            valid_opps = [opp for opp in opportunities if isinstance(opp, dict)]
            valid_opps.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
            for opportunity in valid_opps[:2]:
                title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
                score = float(opportunity.get("score") or 0.0)
                lines.append(f"  - {title} (score: {score:.2f})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_summary_output(run_id: str, markdown_text: str, output_dir: str) -> str:
    path = Path(output_dir) / f"summary-{run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    final_path = str(path)
    log(f"Wrote markdown summary to {final_path}")
    return final_path
