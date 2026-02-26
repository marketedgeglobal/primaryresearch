#!/usr/bin/env python3
"""Render per-theme dashboard pages from historical analysis outputs."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from charting import (
    generate_partner_by_theme_stacked_bar_chart,
    generate_theme_average_score_trend_chart,
    generate_theme_opportunity_count_trend_chart,
)
from log_utils import log


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_run_id(payload: dict[str, Any], file_path: Path) -> str:
    run_id = str(payload.get("run_id") or "").strip()
    if run_id:
        return run_id

    stem = file_path.stem
    if stem.startswith("analysis-"):
        return stem.replace("analysis-", "", 1)
    if stem.startswith("weekly-"):
        return stem.replace("weekly-", "", 1)
    return stem


def _parse_run_datetime(payload: dict[str, Any], file_path: Path) -> datetime:
    generated_utc = str(payload.get("generated_utc") or "").strip()
    if generated_utc:
        try:
            return datetime.fromisoformat(generated_utc.replace("Z", "+00:00"))
        except ValueError:
            pass

    run_id = _extract_run_id(payload, file_path)
    for fmt in ("%Y%m%d-%H%M%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(run_id, fmt)
        except ValueError:
            continue

    return datetime.utcfromtimestamp(file_path.stat().st_mtime)


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "uncategorized"


def _extract_partner(opportunity: dict[str, Any]) -> str:
    for key in ("partner", "partner_name", "organization", "org", "company", "client"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return "Unspecified Partner"


def _extract_score(opportunity: dict[str, Any]) -> float:
    if "score" in opportunity:
        return _safe_float(opportunity.get("score"))

    scores = opportunity.get("scores")
    if isinstance(scores, dict):
        for key in ("opportunity", "overall", "priority", "score"):
            if key in scores:
                return _safe_float(scores.get(key))
    return 0.0


def _extract_theme(opportunity: dict[str, Any], fallback_theme: str | None = None) -> str:
    for key in ("cluster_label", "theme", "category"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()

    tags = opportunity.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                return tag.strip()

    if fallback_theme and fallback_theme.strip():
        return fallback_theme.strip()

    return "Uncategorized"


def _extract_opportunities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = payload.get("ranked_opportunities")
    if isinstance(ranked, list):
        valid = [item for item in ranked if isinstance(item, dict)]
        if valid:
            return valid

    flattened: list[dict[str, Any]] = []
    clusters = payload.get("clusters")
    if isinstance(clusters, list):
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            fallback_theme = str(cluster.get("label") or "").strip() or None
            opportunities = cluster.get("opportunities")
            if not isinstance(opportunities, list):
                continue
            for opportunity in opportunities:
                if not isinstance(opportunity, dict):
                    continue
                entry = dict(opportunity)
                if fallback_theme and not entry.get("cluster_label"):
                    entry["cluster_label"] = fallback_theme
                flattened.append(entry)
        if flattened:
            return flattened

    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _extract_theme_descriptions(payload: dict[str, Any]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    clusters = payload.get("clusters")
    if not isinstance(clusters, list):
        return descriptions

    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        label = str(cluster.get("label") or "").strip()
        if not label:
            continue
        slug = _slugify(label)
        description = str(cluster.get("description") or cluster.get("summary") or "").strip()
        if description:
            descriptions[slug] = description
    return descriptions


def load_analysis_runs(analyses_dir: Path = Path("analyses")) -> list[dict[str, Any]]:
    log(f"Loading historical analyses from {analyses_dir}")
    files = list(analyses_dir.glob("analysis-*.json")) + list(analyses_dir.glob("weekly-*.json"))
    seen_paths: set[Path] = set()
    records: list[dict[str, Any]] = []

    for file_path in files:
        if file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        try:
            payload = _load_json(file_path)
        except Exception as exc:
            log(f"Skipping unreadable analysis file {file_path}: {exc}")
            continue

        records.append(
            {
                "file_path": file_path,
                "analysis": payload,
                "run_id": _extract_run_id(payload, file_path),
                "run_datetime": _parse_run_datetime(payload, file_path),
            }
        )

    records.sort(key=lambda record: (record["run_datetime"], record["run_id"]))
    log(f"Loaded {len(records)} analysis runs")
    return records


def _build_latest_opportunities_markdown(opportunities: list[dict[str, Any]]) -> str:
    if not opportunities:
        return "- No opportunities found for this theme in the latest run."

    lines: list[str] = []
    for opportunity in opportunities[:8]:
        title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
        score = _extract_score(opportunity)
        partner = _extract_partner(opportunity)
        lines.append(f"- **{title}** (score: {score:.2f}, partner: {partner})")
    return "\n".join(lines)


def _build_partner_breakdown_markdown(
    *,
    partner_chart_markdown: str,
    latest_partner_counts: dict[str, int],
) -> str:
    counts_lines: list[str] = []
    sorted_counts = sorted(latest_partner_counts.items(), key=lambda item: (-item[1], item[0]))
    for partner, count in sorted_counts[:10]:
        counts_lines.append(f"- {partner} ({count})")

    counts_markdown = "\n".join(counts_lines) if counts_lines else "- No partner breakdown available."
    if partner_chart_markdown:
        return f"{partner_chart_markdown}\n\n{counts_markdown}"
    return counts_markdown


def _build_theme_history_links(run_points: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for point in sorted(run_points, key=lambda item: str(item.get("run_id", "")), reverse=True):
        run_id = str(point.get("run_id") or "")
        if not run_id:
            continue
        lines.append(f"- [summary-{run_id}.md](../summary-{run_id}.md)")
    return "\n".join(lines) if lines else "- No historical reports for this theme yet."


def _compose_theme_description(label: str, summary: str, latest_count: int) -> str:
    if summary:
        return f"{summary}\n\nLatest run includes **{latest_count}** opportunities for **{label}**."
    return f"Latest run includes **{latest_count}** opportunities for **{label}**."


def render_theme_pages(
    analyses_dir: Path = Path("analyses"),
    template_path: Path = Path("docs/theme_template.md"),
    themes_dir: Path = Path("docs/themes"),
    charts_dir: Path = Path("docs/charts/themes"),
) -> list[Path]:
    log("Starting theme page rendering")
    if not template_path.exists():
        raise FileNotFoundError(f"Missing theme template: {template_path}")

    run_records = load_analysis_runs(analyses_dir=analyses_dir)
    template_text = template_path.read_text(encoding="utf-8")

    themes_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    for existing_file in themes_dir.glob("*.md"):
        existing_file.unlink()

    theme_labels: dict[str, str] = {}
    theme_descriptions: dict[str, str] = {}
    theme_run_points: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in run_records:
        payload = record["analysis"]
        run_id = str(record["run_id"])
        generated_utc = str(payload.get("generated_utc") or record["run_datetime"].isoformat())

        descriptions = _extract_theme_descriptions(payload)
        for slug, description in descriptions.items():
            if description and slug not in theme_descriptions:
                theme_descriptions[slug] = description

        opportunities = _extract_opportunities(payload)
        per_theme: dict[str, dict[str, Any]] = {}

        for opportunity in opportunities:
            theme_label = _extract_theme(opportunity)
            theme_slug = _slugify(theme_label)

            if theme_slug not in per_theme:
                per_theme[theme_slug] = {
                    "theme_label": theme_label,
                    "scores": [],
                    "opportunities": [],
                    "partner_counts": defaultdict(int),
                }

            bucket = per_theme[theme_slug]
            bucket["theme_label"] = theme_label
            score = _extract_score(opportunity)
            bucket["scores"].append(score)
            bucket["opportunities"].append(opportunity)
            partner = _extract_partner(opportunity)
            bucket["partner_counts"][partner] += 1

            if theme_slug not in theme_labels:
                theme_labels[theme_slug] = theme_label

        for theme_slug, bucket in per_theme.items():
            scores = bucket["scores"]
            average_score = (sum(scores) / len(scores)) if scores else 0.0
            ranked = sorted(bucket["opportunities"], key=_extract_score, reverse=True)
            theme_run_points[theme_slug].append(
                {
                    "run_id": run_id,
                    "generated_utc": generated_utc,
                    "opportunity_count": len(bucket["opportunities"]),
                    "average_score": round(average_score, 4),
                    "partner_counts": dict(bucket["partner_counts"]),
                    "latest_opportunities": ranked,
                }
            )

    rendered_paths: list[Path] = []
    for theme_slug in sorted(theme_run_points.keys()):
        run_points = sorted(theme_run_points[theme_slug], key=lambda item: str(item.get("run_id", "")))
        latest = run_points[-1]
        theme_label = theme_labels.get(theme_slug, latest.get("theme_label") or theme_slug.replace("-", " ").title())
        latest_count = int(latest.get("opportunity_count") or 0)
        theme_summary = theme_descriptions.get(theme_slug, "")
        theme_description = _compose_theme_description(theme_label, theme_summary, latest_count)

        log(f"Generating charts for theme '{theme_label}'")
        count_chart = generate_theme_opportunity_count_trend_chart(
            theme_slug=theme_slug,
            theme_label=theme_label,
            run_points=run_points,
            charts_dir=charts_dir,
            image_prefix="../charts/themes",
        )
        score_chart = generate_theme_average_score_trend_chart(
            theme_slug=theme_slug,
            theme_label=theme_label,
            run_points=run_points,
            charts_dir=charts_dir,
            image_prefix="../charts/themes",
        )
        partner_chart = generate_partner_by_theme_stacked_bar_chart(
            theme_slug=theme_slug,
            theme_label=theme_label,
            run_points=run_points,
            charts_dir=charts_dir,
            image_prefix="../charts/themes",
        )

        trend_charts = "\n\n".join([chart for chart in [count_chart, score_chart] if chart])
        if not trend_charts:
            trend_charts = "- No trend charts available for this theme yet."

        partner_breakdown = _build_partner_breakdown_markdown(
            partner_chart_markdown=partner_chart,
            latest_partner_counts=latest.get("partner_counts") if isinstance(latest.get("partner_counts"), dict) else {},
        )

        replacements = {
            "{{theme_label}}": str(theme_label),
            "{{theme_description}}": theme_description,
            "{{latest_opportunities}}": _build_latest_opportunities_markdown(
                latest.get("latest_opportunities") if isinstance(latest.get("latest_opportunities"), list) else []
            ),
            "{{theme_trend_charts}}": trend_charts,
            "{{partner_breakdown}}": partner_breakdown,
            "{{theme_history_links}}": _build_theme_history_links(run_points),
        }

        rendered = template_text
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)

        output_path = themes_dir / f"{theme_slug}.md"
        output_path.write_text(rendered.rstrip() + "\n", encoding="utf-8")
        rendered_paths.append(output_path)
        log(f"Wrote theme page: {output_path}")

    log(f"Completed rendering {len(rendered_paths)} theme pages")
    return rendered_paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render theme-level dashboard pages from historical analyses")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing analysis JSON files")
    parser.add_argument("--template", default="docs/theme_template.md", help="Path to theme template markdown")
    parser.add_argument("--themes-dir", default="docs/themes", help="Directory to write theme markdown pages")
    parser.add_argument("--charts-dir", default="docs/charts/themes", help="Directory to write theme chart images")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    render_theme_pages(
        analyses_dir=Path(args.analyses_dir),
        template_path=Path(args.template),
        themes_dir=Path(args.themes_dir),
        charts_dir=Path(args.charts_dir),
    )


if __name__ == "__main__":
    main()
