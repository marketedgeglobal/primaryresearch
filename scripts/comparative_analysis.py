#!/usr/bin/env python3
"""Cross-partner x cross-theme comparative analytics across historical analyses."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

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
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-") or "uncategorized"


def _extract_partner(opportunity: dict[str, Any]) -> str:
    for key in ("partner", "partner_name", "organization", "org", "company", "client"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return "Unspecified Partner"


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


def _extract_score(opportunity: dict[str, Any]) -> float:
    if "score" in opportunity:
        return _safe_float(opportunity.get("score"))

    scores = opportunity.get("scores")
    if isinstance(scores, dict):
        for key in ("opportunity", "overall", "priority", "score"):
            if key in scores:
                return _safe_float(scores.get(key))
    return 0.0


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


def load_analysis_runs(analyses_dir: Path = Path("analyses")) -> list[dict[str, Any]]:
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
    return records


def _summarize_run(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    opportunities = _extract_opportunities(payload)

    matrix_counts: dict[str, dict[str, int]] = {}
    matrix_scores_sum: dict[str, dict[str, float]] = {}

    for opportunity in opportunities:
        partner = _extract_partner(opportunity)
        theme = _extract_theme(opportunity)
        score = _extract_score(opportunity)

        matrix_counts.setdefault(partner, {})
        matrix_scores_sum.setdefault(partner, {})

        matrix_counts[partner][theme] = matrix_counts[partner].get(theme, 0) + 1
        matrix_scores_sum[partner][theme] = matrix_scores_sum[partner].get(theme, 0.0) + score

    matrix_average_scores: dict[str, dict[str, float]] = {}
    for partner, theme_counts in matrix_counts.items():
        matrix_average_scores[partner] = {}
        for theme, count in theme_counts.items():
            total_score = matrix_scores_sum.get(partner, {}).get(theme, 0.0)
            avg_score = (total_score / count) if count else 0.0
            matrix_average_scores[partner][theme] = round(avg_score, 4)

    return {
        "run_id": run_id,
        "opportunities": opportunities,
        "counts": matrix_counts,
        "average_scores": matrix_average_scores,
    }


def _matrix_delta(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    partners: list[str],
    themes: list[str],
    as_float: bool,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for partner in partners:
        out[partner] = {}
        current_row = current.get(partner) if isinstance(current.get(partner), dict) else {}
        previous_row = previous.get(partner) if isinstance(previous.get(partner), dict) else {}
        for theme in themes:
            current_value = current_row.get(theme, 0.0 if as_float else 0)
            previous_value = previous_row.get(theme, 0.0 if as_float else 0)
            delta = _safe_float(current_value) - _safe_float(previous_value)
            out[partner][theme] = round(delta, 4) if as_float else int(delta)
    return out


def _build_partner_strengths(
    partners: list[str],
    themes: list[str],
    counts: dict[str, dict[str, int]],
    average_scores: dict[str, dict[str, float]],
    delta_counts: dict[str, dict[str, int]],
    delta_scores: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    theme_average_reference: dict[str, float] = {}
    for theme in themes:
        weighted_sum = 0.0
        total_count = 0
        for partner in partners:
            count = int((counts.get(partner) or {}).get(theme, 0) or 0)
            avg_score = _safe_float((average_scores.get(partner) or {}).get(theme, 0.0))
            weighted_sum += avg_score * count
            total_count += count
        theme_average_reference[theme] = (weighted_sum / total_count) if total_count else 0.0

    strengths: list[dict[str, Any]] = []
    for partner in partners:
        partner_counts = counts.get(partner) if isinstance(counts.get(partner), dict) else {}
        partner_scores = average_scores.get(partner) if isinstance(average_scores.get(partner), dict) else {}
        partner_total = sum(int(value or 0) for value in partner_counts.values())
        if partner_total == 0:
            continue

        weighted_score_sum = 0.0
        for theme, count in partner_counts.items():
            weighted_score_sum += int(count or 0) * _safe_float(partner_scores.get(theme, 0.0))
        partner_avg_score = weighted_score_sum / partner_total if partner_total else 0.0

        strong_themes: list[dict[str, Any]] = []
        for theme in themes:
            count = int(partner_counts.get(theme, 0) or 0)
            if count == 0:
                continue
            avg_score = _safe_float(partner_scores.get(theme, 0.0))
            theme_ref = theme_average_reference.get(theme, 0.0)
            if avg_score < theme_ref:
                continue
            strong_themes.append(
                {
                    "theme": theme,
                    "opportunity_count": count,
                    "average_score": round(avg_score, 4),
                    "delta_count": int((delta_counts.get(partner) or {}).get(theme, 0) or 0),
                    "delta_average_score": round(_safe_float((delta_scores.get(partner) or {}).get(theme, 0.0)), 4),
                }
            )

        strong_themes.sort(
            key=lambda item: (
                -_safe_float(item.get("average_score")),
                -int(item.get("opportunity_count") or 0),
                str(item.get("theme") or ""),
            )
        )

        strengths.append(
            {
                "partner": partner,
                "total_opportunities": partner_total,
                "average_score": round(partner_avg_score, 4),
                "strong_themes": strong_themes,
            }
        )

    strengths.sort(
        key=lambda item: (
            -len(item.get("strong_themes") if isinstance(item.get("strong_themes"), list) else []),
            -_safe_float(item.get("average_score")),
            str(item.get("partner") or ""),
        )
    )
    return strengths


def _build_theme_strengths(
    partners: list[str],
    themes: list[str],
    counts: dict[str, dict[str, int]],
    average_scores: dict[str, dict[str, float]],
    delta_counts: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    strengths: list[dict[str, Any]] = []

    for theme in themes:
        leaders: list[dict[str, Any]] = []
        total_count = 0
        weighted_sum = 0.0
        for partner in partners:
            count = int((counts.get(partner) or {}).get(theme, 0) or 0)
            if count <= 0:
                continue
            avg_score = _safe_float((average_scores.get(partner) or {}).get(theme, 0.0))
            total_count += count
            weighted_sum += avg_score * count
            leaders.append(
                {
                    "partner": partner,
                    "opportunity_count": count,
                    "average_score": round(avg_score, 4),
                    "delta_count": int((delta_counts.get(partner) or {}).get(theme, 0) or 0),
                }
            )

        leaders.sort(
            key=lambda item: (
                -_safe_float(item.get("average_score")),
                -int(item.get("opportunity_count") or 0),
                str(item.get("partner") or ""),
            )
        )

        if total_count == 0:
            continue

        strengths.append(
            {
                "theme": theme,
                "total_opportunities": total_count,
                "average_score": round((weighted_sum / total_count) if total_count else 0.0, 4),
                "leading_partners": leaders[:5],
            }
        )

    strengths.sort(
        key=lambda item: (
            -int(item.get("total_opportunities") or 0),
            -_safe_float(item.get("average_score")),
            str(item.get("theme") or ""),
        )
    )
    return strengths


def _build_week_over_week_rows(
    partners: list[str],
    themes: list[str],
    current_counts: dict[str, dict[str, int]],
    previous_counts: dict[str, dict[str, int]],
    current_scores: dict[str, dict[str, float]],
    previous_scores: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for partner in partners:
        for theme in themes:
            current_count = int((current_counts.get(partner) or {}).get(theme, 0) or 0)
            previous_count = int((previous_counts.get(partner) or {}).get(theme, 0) or 0)
            current_avg = _safe_float((current_scores.get(partner) or {}).get(theme, 0.0))
            previous_avg = _safe_float((previous_scores.get(partner) or {}).get(theme, 0.0))
            delta_count = current_count - previous_count
            delta_avg = round(current_avg - previous_avg, 4)

            if current_count == 0 and previous_count == 0 and delta_avg == 0.0:
                continue

            rows.append(
                {
                    "partner": partner,
                    "theme": theme,
                    "previous_count": previous_count,
                    "current_count": current_count,
                    "delta_count": delta_count,
                    "previous_average_score": round(previous_avg, 4),
                    "current_average_score": round(current_avg, 4),
                    "delta_average_score": delta_avg,
                }
            )

    rows.sort(
        key=lambda item: (
            -abs(int(item.get("delta_count") or 0)),
            -abs(_safe_float(item.get("delta_average_score") or 0.0)),
            str(item.get("partner") or ""),
            str(item.get("theme") or ""),
        )
    )
    return rows


def build_comparative_data(analyses_dir: Path = Path("analyses")) -> dict[str, Any]:
    run_records = load_analysis_runs(analyses_dir=analyses_dir)
    if not run_records:
        return {
            "runs": [],
            "partners": [],
            "themes": [],
            "matrix": {
                "counts": {},
                "average_scores": {},
                "delta_counts": {},
                "delta_scores": {},
            },
            "partner_strengths": [],
            "theme_strengths": [],
            "week_over_week": [],
        }

    latest_record = run_records[-1]
    previous_record = run_records[-2] if len(run_records) >= 2 else None

    latest_summary = _summarize_run(latest_record["analysis"], latest_record["run_id"])
    previous_summary = (
        _summarize_run(previous_record["analysis"], previous_record["run_id"]) if previous_record is not None else None
    )

    latest_counts = latest_summary["counts"] if isinstance(latest_summary.get("counts"), dict) else {}
    latest_scores = latest_summary["average_scores"] if isinstance(latest_summary.get("average_scores"), dict) else {}

    previous_counts = previous_summary["counts"] if isinstance(previous_summary and previous_summary.get("counts"), dict) else {}
    previous_scores = (
        previous_summary["average_scores"]
        if isinstance(previous_summary and previous_summary.get("average_scores"), dict)
        else {}
    )

    partners = sorted(
        set(latest_counts.keys()) | set(previous_counts.keys()),
        key=lambda value: value.lower(),
    )

    themes_set: set[str] = set()
    for partner in partners:
        latest_partner_counts = latest_counts.get(partner) if isinstance(latest_counts.get(partner), dict) else {}
        previous_partner_counts = (
            previous_counts.get(partner) if isinstance(previous_counts.get(partner), dict) else {}
        )
        themes_set.update(str(theme) for theme in latest_partner_counts.keys())
        themes_set.update(str(theme) for theme in previous_partner_counts.keys())
    themes = sorted(themes_set, key=lambda value: value.lower())

    for partner in partners:
        latest_counts.setdefault(partner, {})
        latest_scores.setdefault(partner, {})
        previous_counts.setdefault(partner, {})
        previous_scores.setdefault(partner, {})
        for theme in themes:
            latest_counts[partner].setdefault(theme, 0)
            latest_scores[partner].setdefault(theme, 0.0)
            previous_counts[partner].setdefault(theme, 0)
            previous_scores[partner].setdefault(theme, 0.0)

    delta_counts = _matrix_delta(latest_counts, previous_counts, partners, themes, as_float=False)
    delta_scores = _matrix_delta(latest_scores, previous_scores, partners, themes, as_float=True)

    partner_strengths = _build_partner_strengths(
        partners=partners,
        themes=themes,
        counts=latest_counts,
        average_scores=latest_scores,
        delta_counts=delta_counts,
        delta_scores=delta_scores,
    )

    theme_strengths = _build_theme_strengths(
        partners=partners,
        themes=themes,
        counts=latest_counts,
        average_scores=latest_scores,
        delta_counts=delta_counts,
    )

    week_over_week = _build_week_over_week_rows(
        partners=partners,
        themes=themes,
        current_counts=latest_counts,
        previous_counts=previous_counts,
        current_scores=latest_scores,
        previous_scores=previous_scores,
    )

    return {
        "runs": [
            {
                "current": latest_summary["run_id"],
                "previous": previous_summary["run_id"] if previous_summary is not None else None,
            }
        ],
        "partners": partners,
        "themes": themes,
        "matrix": {
            "counts": latest_counts,
            "average_scores": latest_scores,
            "delta_counts": delta_counts,
            "delta_scores": delta_scores,
        },
        "partner_strengths": partner_strengths,
        "theme_strengths": theme_strengths,
        "week_over_week": week_over_week,
    }


def write_comparative_output(comparative_data: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(comparative_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Wrote comparative analysis output to {output_path}")
    return output_path


def _load_chart_markdown(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _build_delta_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "| Partner | Theme | Prev Count | Curr Count | Delta | Prev Avg | Curr Avg | Delta Avg |\n| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n| - | - | 0 | 0 | 0 | 0.00 | 0.00 | 0.00 |"

    lines = [
        "| Partner | Theme | Prev Count | Curr Count | Delta | Prev Avg | Curr Avg | Delta Avg |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:25]:
        if not isinstance(row, dict):
            continue
        delta_count = int(row.get("delta_count") or 0)
        delta_score = _safe_float(row.get("delta_average_score") or 0.0)
        count_sign = "+" if delta_count > 0 else ""
        score_sign = "+" if delta_score > 0 else ""
        lines.append(
            "| {partner} | {theme} | {prev_count} | {curr_count} | {count_sign}{delta_count} | {prev_avg:.2f} | {curr_avg:.2f} | {score_sign}{delta_score:.2f} |".format(
                partner=str(row.get("partner") or "-"),
                theme=str(row.get("theme") or "-"),
                prev_count=int(row.get("previous_count") or 0),
                curr_count=int(row.get("current_count") or 0),
                count_sign=count_sign,
                delta_count=delta_count,
                prev_avg=_safe_float(row.get("previous_average_score") or 0.0),
                curr_avg=_safe_float(row.get("current_average_score") or 0.0),
                score_sign=score_sign,
                delta_score=delta_score,
            )
        )
    return "\n".join(lines)


def _build_partner_specialization_summaries(strengths: list[dict[str, Any]]) -> str:
    if not strengths:
        return "- No partner specialization insights available yet."

    lines: list[str] = []
    for entry in strengths[:8]:
        if not isinstance(entry, dict):
            continue
        partner = str(entry.get("partner") or "Unknown Partner")
        strong_themes = entry.get("strong_themes") if isinstance(entry.get("strong_themes"), list) else []
        if not strong_themes:
            lines.append(f"- **{partner}**: no standout themes in the latest run.")
            continue
        top_themes = ", ".join(str(theme.get("theme") or "Uncategorized") for theme in strong_themes[:3])
        lines.append(
            f"- **{partner}**: strongest in {top_themes} (themes above benchmark: {len(strong_themes)})."
        )
    return "\n".join(lines) if lines else "- No partner specialization insights available yet."


def _build_theme_dominance_summaries(theme_strengths: list[dict[str, Any]]) -> str:
    if not theme_strengths:
        return "- No theme dominance insights available yet."

    lines: list[str] = []
    for entry in theme_strengths[:10]:
        if not isinstance(entry, dict):
            continue
        theme = str(entry.get("theme") or "Uncategorized")
        leaders = entry.get("leading_partners") if isinstance(entry.get("leading_partners"), list) else []
        if not leaders:
            lines.append(f"- **{theme}**: no leading partner identified.")
            continue

        top = leaders[0] if isinstance(leaders[0], dict) else {}
        partner = str(top.get("partner") or "Unknown Partner")
        score = _safe_float(top.get("average_score") or 0.0)
        count = int(top.get("opportunity_count") or 0)
        lines.append(f"- **{theme}**: led by **{partner}** (avg score {score:.2f}, opportunities {count}).")

    return "\n".join(lines) if lines else "- No theme dominance insights available yet."


def _build_partner_and_theme_links(docs_dir: Path) -> str:
    partner_links: list[str] = []
    theme_links: list[str] = []

    partners_dir = docs_dir / "partners"
    if partners_dir.exists():
        for path in sorted(partners_dir.glob("*.md")):
            label = path.stem.replace("-", " ").title()
            partner_links.append(f"- [{label}](partners/{path.name})")

    themes_dir = docs_dir / "themes"
    if themes_dir.exists():
        for path in sorted(themes_dir.glob("*.md")):
            label = path.stem.replace("-", " ").title()
            theme_links.append(f"- [{label}](themes/{path.name})")

    partner_section = "\n".join(partner_links[:20]) if partner_links else "- No partner pages available yet."
    theme_section = "\n".join(theme_links[:20]) if theme_links else "- No theme pages available yet."

    return "\n".join(["### Partner Pages", "", partner_section, "", "### Theme Pages", "", theme_section])


def render_comparative_markdown(
    comparative_data: dict[str, Any],
    output_path: Path,
    docs_dir: Path = Path("docs"),
    charts_markdown: str = "",
) -> Path:
    runs = comparative_data.get("runs") if isinstance(comparative_data.get("runs"), list) else []
    run_info = runs[0] if runs and isinstance(runs[0], dict) else {}
    current_run = str(run_info.get("current") or "unknown")
    previous_run = str(run_info.get("previous") or "n/a")

    week_over_week = (
        comparative_data.get("week_over_week") if isinstance(comparative_data.get("week_over_week"), list) else []
    )
    partner_strengths = (
        comparative_data.get("partner_strengths")
        if isinstance(comparative_data.get("partner_strengths"), list)
        else []
    )
    theme_strengths = (
        comparative_data.get("theme_strengths") if isinstance(comparative_data.get("theme_strengths"), list) else []
    )

    heatmap_markdown = ""
    for block in charts_markdown.split("\n\n"):
        if "Heatmap" in block and "Delta" not in block:
            heatmap_markdown = block.strip()
            break

    lines: list[str] = [
        "# Cross-Partner × Cross-Theme Comparative Analytics",
        "",
        f"Current run: **{current_run}** | Previous run: **{previous_run}**",
        "",
        "## Partner × Theme Heatmap",
        "",
    ]

    if heatmap_markdown:
        lines.append(heatmap_markdown)
    else:
        lines.append("- Heatmap will appear after comparative chart generation.")

    if charts_markdown:
        lines.extend(["", "## Comparative Charts", "", charts_markdown])

    lines.extend(
        [
            "",
            "## Week-over-Week Delta Table",
            "",
            _build_delta_table(week_over_week),
            "",
            "## Partner Specialization Summaries",
            "",
            _build_partner_specialization_summaries(partner_strengths),
            "",
            "## Theme Dominance Summaries",
            "",
            _build_theme_dominance_summaries(theme_strengths),
            "",
            "## Partner and Theme Pages",
            "",
            _build_partner_and_theme_links(docs_dir=docs_dir),
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    log(f"Wrote comparative markdown to {output_path}")
    return output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cross-partner x cross-theme comparative analytics")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing analysis JSON files")
    parser.add_argument("--output", default="docs/comparative_data.json", help="Path to write comparative JSON")
    parser.add_argument("--markdown-output", default="", help="Optional path to write comparative markdown")
    parser.add_argument("--charts-markdown", default="", help="Optional comparative chart markdown file path")
    parser.add_argument("--docs-dir", default="docs", help="Docs directory for page links")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    comparative_data = build_comparative_data(analyses_dir=Path(args.analyses_dir))
    write_comparative_output(comparative_data, output_path=Path(args.output))

    if args.markdown_output:
        chart_markdown = _load_chart_markdown(Path(args.charts_markdown)) if args.charts_markdown else ""
        render_comparative_markdown(
            comparative_data=comparative_data,
            output_path=Path(args.markdown_output),
            docs_dir=Path(args.docs_dir),
            charts_markdown=chart_markdown,
        )


if __name__ == "__main__":
    main()
