#!/usr/bin/env python3
"""Automated insight and narrative generation from trend and comparative outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import load_insights_config
from log_utils import log
from output_writer import write_json
from summary_generator import build_markdown_summary, write_summary_output
from trend_analysis import build_trend_data


DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "emergence": {
        "title": "Emerging momentum in {theme}",
        "narrative": "{theme} grew from {previous_count} to {current_count} opportunities, signaling fresh momentum in this cycle.",
    },
    "decline": {
        "title": "Decline detected in {theme}",
        "narrative": "{theme} dropped from {previous_count} to {current_count} opportunities, indicating a potential slowdown.",
    },
    "divergence": {
        "title": "Partner divergence in {theme}",
        "narrative": "Performance diverges across partners in {theme}, with a score spread of {score_spread:.2f}.",
    },
    "concentration": {
        "title": "Concentration risk in {theme}",
        "narrative": "{partner} now accounts for {share_pct:.1f}% of {theme} opportunities ({count}/{total_count}), indicating concentration.",
    },
    "anomaly": {
        "title": "Anomalous week-over-week change", 
        "narrative": "{partner} in {theme} shifted by {delta_count:+d} opportunities week-over-week, above expected volatility.",
    },
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_templates(path: str | Path | None) -> dict[str, dict[str, str]]:
    templates = {key: dict(value) for key, value in DEFAULT_TEMPLATES.items()}
    if not path:
        return templates

    template_path = Path(path)
    if not template_path.exists():
        return templates

    current_type: str | None = None
    for raw_line in template_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            current_type = stripped[:-1].strip()
            templates.setdefault(current_type, {})
            continue

        if current_type is None or ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        cleaned = value.strip().strip('"').strip("'")
        templates[current_type][key.strip()] = cleaned

    return templates


def _extract_opportunities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = payload.get("ranked_opportunities")
    if isinstance(ranked, list):
        valid = [item for item in ranked if isinstance(item, dict)]
        if valid:
            return valid

    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]

    return []


def _extract_theme(opportunity: dict[str, Any]) -> str:
    for key in ("cluster_label", "theme", "category"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

    tags = opportunity.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                return tag.strip()

    return "Uncategorized"


def _extract_partner(opportunity: dict[str, Any]) -> str:
    for key in ("partner", "partner_name", "organization", "org", "company", "client"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return "Unspecified Partner"


def _extract_supporting_opportunities(
    opportunities: list[dict[str, Any]],
    *,
    theme: str | None = None,
    partner: str | None = None,
    limit: int = 3,
) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for opportunity in opportunities:
        if theme and _extract_theme(opportunity) != theme:
            continue
        if partner and _extract_partner(opportunity) != partner:
            continue

        title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
        url = str(opportunity.get("url") or opportunity.get("link") or opportunity.get("opportunity_url") or "")
        filtered.append({"title": title, "url": url})
        if len(filtered) >= limit:
            break
    return filtered


def _new_insight(
    *,
    insight_type: str,
    index: int,
    template: dict[str, str],
    evidence: list[dict[str, Any]],
    confidence: float,
    run_ids: list[str],
    context: dict[str, Any],
) -> dict[str, Any]:
    title = template.get("title", DEFAULT_TEMPLATES[insight_type]["title"]).format(**context)
    narrative = template.get("narrative", DEFAULT_TEMPLATES[insight_type]["narrative"]).format(**context)
    return {
        "id": f"{insight_type}-{index}",
        "type": insight_type,
        "title": title,
        "narrative": narrative,
        "evidence": evidence,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "run_ids": run_ids,
    }


def generate_insights(
    analysis_history: list[dict[str, Any]],
    comparative_data: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    min_count = _safe_int(config.get("insight_min_count") or config.get("min_count") or 3)
    delta_threshold = _safe_float(config.get("insight_delta_threshold") or config.get("delta_threshold") or 2.0)
    concentration_threshold = _safe_float(config.get("insight_concentration_threshold") or 0.6)
    anomaly_multiplier = _safe_float(config.get("insight_anomaly_multiplier") or 2.0)
    templates = _load_templates(config.get("insight_template_path"))

    if len(analysis_history) < 1:
        return []

    current = analysis_history[-1]
    previous = analysis_history[-2] if len(analysis_history) > 1 else {}
    run_ids = [str(previous.get("run_id") or ""), str(current.get("run_id") or "")]
    run_ids = [run_id for run_id in run_ids if run_id]

    current_theme_counts = current.get("per_theme_counts") if isinstance(current.get("per_theme_counts"), dict) else {}
    previous_theme_counts = previous.get("per_theme_counts") if isinstance(previous.get("per_theme_counts"), dict) else {}

    latest_analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else {}
    latest_opportunities = _extract_opportunities(latest_analysis)

    insights: list[dict[str, Any]] = []

    all_themes = sorted(set(current_theme_counts.keys()) | set(previous_theme_counts.keys()))
    for theme in all_themes:
        previous_count = _safe_int(previous_theme_counts.get(theme, 0))
        current_count = _safe_int(current_theme_counts.get(theme, 0))
        delta = current_count - previous_count

        if current_count >= min_count and delta >= delta_threshold:
            confidence = min(0.95, 0.45 + (delta / max(delta_threshold, 1.0)) * 0.2)
            evidence = [
                {
                    "theme": theme,
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "delta": delta,
                    "opportunities": _extract_supporting_opportunities(latest_opportunities, theme=theme),
                }
            ]
            insights.append(
                _new_insight(
                    insight_type="emergence",
                    index=len([item for item in insights if item["type"] == "emergence"]) + 1,
                    template=templates.get("emergence", DEFAULT_TEMPLATES["emergence"]),
                    evidence=evidence,
                    confidence=confidence,
                    run_ids=run_ids,
                    context={
                        "theme": theme,
                        "previous_count": previous_count,
                        "current_count": current_count,
                    },
                )
            )

        if previous_count >= min_count and -delta >= delta_threshold:
            confidence = min(0.95, 0.45 + ((-delta) / max(delta_threshold, 1.0)) * 0.2)
            evidence = [
                {
                    "theme": theme,
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "delta": delta,
                    "opportunities": _extract_supporting_opportunities(latest_opportunities, theme=theme),
                }
            ]
            insights.append(
                _new_insight(
                    insight_type="decline",
                    index=len([item for item in insights if item["type"] == "decline"]) + 1,
                    template=templates.get("decline", DEFAULT_TEMPLATES["decline"]),
                    evidence=evidence,
                    confidence=confidence,
                    run_ids=run_ids,
                    context={
                        "theme": theme,
                        "previous_count": previous_count,
                        "current_count": current_count,
                    },
                )
            )

    matrix = comparative_data.get("matrix") if isinstance(comparative_data.get("matrix"), dict) else {}
    counts_matrix = matrix.get("counts") if isinstance(matrix.get("counts"), dict) else {}
    score_matrix = matrix.get("average_scores") if isinstance(matrix.get("average_scores"), dict) else {}

    themes: set[str] = set()
    for partner, values in counts_matrix.items():
        if isinstance(values, dict):
            themes.update(str(theme) for theme in values.keys())

    for theme in sorted(themes):
        theme_scores: list[tuple[str, float, int]] = []
        total = 0
        max_partner = ""
        max_count = 0

        for partner, counts in counts_matrix.items():
            if not isinstance(counts, dict):
                continue
            count = _safe_int(counts.get(theme, 0))
            if count <= 0:
                continue
            avg_score = _safe_float((score_matrix.get(partner) or {}).get(theme, 0.0))
            theme_scores.append((partner, avg_score, count))
            total += count
            if count > max_count:
                max_count = count
                max_partner = str(partner)

        if not theme_scores or total < min_count:
            continue

        score_values = [entry[1] for entry in theme_scores]
        spread = max(score_values) - min(score_values)
        divergence_threshold = max(0.15, min(0.5, delta_threshold / 10.0))
        if spread >= divergence_threshold and len(theme_scores) >= 2:
            confidence = min(0.95, 0.5 + spread)
            evidence = [
                {
                    "theme": theme,
                    "score_spread": round(spread, 4),
                    "partner_scores": [
                        {"partner": partner, "average_score": round(score, 4), "count": count}
                        for partner, score, count in sorted(theme_scores, key=lambda item: item[1], reverse=True)
                    ],
                    "opportunities": _extract_supporting_opportunities(latest_opportunities, theme=theme),
                }
            ]
            insights.append(
                _new_insight(
                    insight_type="divergence",
                    index=len([item for item in insights if item["type"] == "divergence"]) + 1,
                    template=templates.get("divergence", DEFAULT_TEMPLATES["divergence"]),
                    evidence=evidence,
                    confidence=confidence,
                    run_ids=run_ids,
                    context={"theme": theme, "score_spread": spread},
                )
            )

        share = (max_count / total) if total else 0.0
        if share >= concentration_threshold:
            confidence = min(0.95, 0.5 + share / 2)
            evidence = [
                {
                    "theme": theme,
                    "partner": max_partner,
                    "count": max_count,
                    "total_count": total,
                    "share": round(share, 4),
                    "opportunities": _extract_supporting_opportunities(
                        latest_opportunities,
                        theme=theme,
                        partner=max_partner,
                    ),
                }
            ]
            insights.append(
                _new_insight(
                    insight_type="concentration",
                    index=len([item for item in insights if item["type"] == "concentration"]) + 1,
                    template=templates.get("concentration", DEFAULT_TEMPLATES["concentration"]),
                    evidence=evidence,
                    confidence=confidence,
                    run_ids=run_ids,
                    context={
                        "theme": theme,
                        "partner": max_partner,
                        "count": max_count,
                        "total_count": total,
                        "share_pct": share * 100,
                    },
                )
            )

    week_over_week = comparative_data.get("week_over_week") if isinstance(comparative_data.get("week_over_week"), list) else []
    anomaly_delta_threshold = max(min_count, int(round(delta_threshold * anomaly_multiplier)))
    for row in week_over_week:
        if not isinstance(row, dict):
            continue
        delta_count = _safe_int(row.get("delta_count", 0))
        delta_average_score = _safe_float(row.get("delta_average_score", 0.0))
        if abs(delta_count) < anomaly_delta_threshold and abs(delta_average_score) < 0.35:
            continue

        partner = str(row.get("partner") or "Unspecified Partner")
        theme = str(row.get("theme") or "Uncategorized")
        confidence = min(0.95, 0.45 + (abs(delta_count) / max(anomaly_delta_threshold, 1)) * 0.2)
        evidence = [
            {
                "partner": partner,
                "theme": theme,
                "previous_count": _safe_int(row.get("previous_count", 0)),
                "current_count": _safe_int(row.get("current_count", 0)),
                "delta_count": delta_count,
                "delta_average_score": round(delta_average_score, 4),
                "opportunities": _extract_supporting_opportunities(
                    latest_opportunities,
                    theme=theme,
                    partner=partner,
                ),
            }
        ]
        insights.append(
            _new_insight(
                insight_type="anomaly",
                index=len([item for item in insights if item["type"] == "anomaly"]) + 1,
                template=templates.get("anomaly", DEFAULT_TEMPLATES["anomaly"]),
                evidence=evidence,
                confidence=confidence,
                run_ids=run_ids,
                context={"partner": partner, "theme": theme, "delta_count": delta_count},
            )
        )

    insights.sort(key=lambda item: (float(item.get("confidence") or 0.0), str(item.get("type") or "")), reverse=True)
    return insights


def render_insights_markdown(insights: list[dict[str, Any]], run_metadata: dict[str, Any]) -> str:
    run_id = str(run_metadata.get("run_id") or "")
    generated_utc = str(run_metadata.get("generated_utc") or "")

    lines: list[str] = [f"# Automated Insights — {run_id}", ""]
    if generated_utc:
        lines.extend([f"Generated UTC: {generated_utc}", ""])

    if not insights:
        lines.extend(["No automated insights met thresholds for this run.", ""])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(["## Top Automated Insights", ""])
    for index, insight in enumerate(insights, start=1):
        title = str(insight.get("title") or f"Insight {index}")
        insight_type = str(insight.get("type") or "unknown")
        confidence = _safe_float(insight.get("confidence", 0.0))
        narrative = str(insight.get("narrative") or "")
        evidence = insight.get("evidence") if isinstance(insight.get("evidence"), list) else []

        lines.append(f"### {index}. {title}")
        lines.append("")
        lines.append(f"- **Type:** {insight_type}")
        lines.append(f"- **Confidence:** {confidence:.2f}")
        lines.append("")
        if narrative:
            lines.append(narrative)
            lines.append("")

        lines.extend(
            [
                "#### Evidence",
                "",
                "| Metric | Value |",
                "| --- | --- |",
            ]
        )
        for item in evidence:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                if key == "opportunities":
                    continue
                lines.append(f"| {key.replace('_', ' ').title()} | {value} |")
        lines.append("")

        supporting: list[dict[str, str]] = []
        for item in evidence:
            if isinstance(item, dict) and isinstance(item.get("opportunities"), list):
                supporting.extend([entry for entry in item["opportunities"] if isinstance(entry, dict)])

        if supporting:
            lines.append("#### Supporting Opportunities")
            lines.append("")
            for opportunity in supporting[:5]:
                title_text = str(opportunity.get("title") or "Untitled")
                url = str(opportunity.get("url") or "").strip()
                if url:
                    lines.append(f"- [{title_text}]({url})")
                else:
                    lines.append(f"- {title_text}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_insights_output(run_id: str, insights: list[dict[str, Any]], output_dir: str) -> dict[str, str]:
    analysis_path = Path(output_dir) / f"insights-{run_id}.json"
    docs_path = Path("docs") / f"insights-{run_id}.md"

    payload = {
        "run_id": run_id,
        "insights": insights,
    }
    write_json(str(analysis_path), payload)

    markdown = render_insights_markdown(insights, {"run_id": run_id})
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(markdown, encoding="utf-8")
    log(f"Wrote insights markdown to {docs_path}")

    return {
        "analysis_json": str(analysis_path),
        "docs_markdown": str(docs_path),
    }


def _attach_insights_to_analysis(analysis: dict[str, Any], run_id: str, insights: list[dict[str, Any]]) -> dict[str, Any]:
    updated = dict(analysis)
    updated["automated_insights"] = insights[:3]
    updated["insights_doc_path"] = f"insights-{run_id}.md"
    return updated


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate automated insights from comparative and trend outputs")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing historical analyses")
    parser.add_argument("--comparative-data", default="docs/comparative_data.json", help="Comparative data JSON path")
    parser.add_argument("--trend-data", default="docs/trend_data.json", help="Trend data JSON path")
    parser.add_argument("--output-dir", default="analyses", help="Directory for insights JSON output")
    parser.add_argument("--analysis-json", default="", help="Optional analysis JSON file to enrich")
    parser.add_argument("--weekly-analysis-json", default="", help="Optional weekly analysis JSON file to enrich")
    parser.add_argument("--summary-path", default="", help="Optional summary markdown output path to refresh")
    parser.add_argument("--docs-summary-path", default="", help="Optional docs summary markdown path to refresh")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    insights_cfg = load_insights_config()

    trend_data_path = Path(args.trend_data)
    if trend_data_path.exists():
        trend_data = _load_json(trend_data_path)
    else:
        trend_data = build_trend_data(analyses_dir=Path(args.analyses_dir))

    analysis_history = trend_data.get("runs") if isinstance(trend_data.get("runs"), list) else []
    if analysis_history:
        latest_run_id = str(analysis_history[-1].get("run_id") or "")
        latest_analysis_path = Path(args.analyses_dir) / f"weekly-{latest_run_id}.json"
        if latest_analysis_path.exists() and isinstance(analysis_history[-1], dict):
            analysis_history[-1] = dict(analysis_history[-1])
            analysis_history[-1]["analysis"] = _load_json(latest_analysis_path)

    comparative_data = _load_json(Path(args.comparative_data))
    insights = generate_insights(analysis_history, comparative_data, insights_cfg)
    paths = write_insights_output(args.run_id, insights, args.output_dir)

    for analysis_path_str in (args.analysis_json, args.weekly_analysis_json):
        if not analysis_path_str:
            continue
        analysis_path = Path(analysis_path_str)
        if not analysis_path.exists():
            continue
        analysis_payload = _load_json(analysis_path)
        updated = _attach_insights_to_analysis(analysis_payload, args.run_id, insights)
        write_json(str(analysis_path), updated)

        for summary_path in (args.summary_path, args.docs_summary_path):
            if not summary_path:
                continue
            summary_text = build_markdown_summary(updated, args.run_id)
            write_summary_output(args.run_id, summary_text, str(Path(summary_path).parent))

    log(f"Generated {len(insights)} automated insights")
    log(f"Insights outputs: {paths}")


if __name__ == "__main__":
    main()
