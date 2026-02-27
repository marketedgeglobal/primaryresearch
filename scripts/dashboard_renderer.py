#!/usr/bin/env python3
"""Render the GitHub Pages dashboard from template and latest outputs."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from charting import generate_trend_charts
from log_utils import log
from trend_analysis import build_trend_data


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_latest_analysis(run_id: str | None, analyses_dir: Path) -> dict[str, Any]:
    if run_id:
        preferred = analyses_dir / f"weekly-{run_id}.json"
        if preferred.exists():
            log(f"Loaded latest analysis from {preferred}")
            return _load_json(preferred)

    fallback = _find_latest_file(analyses_dir, "weekly-*.json")
    if fallback is None:
        raise FileNotFoundError(f"No weekly analysis JSON found in {analyses_dir}")

    log(f"Loaded fallback analysis from {fallback}")
    return _load_json(fallback)


def _load_latest_summary(run_id: str | None, docs_dir: Path) -> str:
    if run_id:
        preferred = docs_dir / f"summary-{run_id}.md"
        if preferred.exists():
            log(f"Loaded latest summary from {preferred}")
            return preferred.read_text(encoding="utf-8").strip()

    fallback = _find_latest_file(docs_dir, "summary-*.md")
    if fallback is None:
        raise FileNotFoundError(f"No summary markdown found in {docs_dir}")

    log(f"Loaded fallback summary from {fallback}")
    return fallback.read_text(encoding="utf-8").strip()


def load_dashboard_inputs(
    analyses_dir: Path = Path("analyses"),
    docs_dir: Path = Path("docs"),
    metadata_path: Path = Path("run_metadata.json"),
) -> dict[str, Any]:
    log("Loading dashboard inputs")

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata file: {metadata_path}")

    metadata = _load_json(metadata_path)
    run_id = str(metadata.get("run_id") or "")

    analysis = _load_latest_analysis(run_id or None, analyses_dir)
    summary_markdown = _load_latest_summary(run_id or None, docs_dir)

    history_path = docs_dir / "history.md"
    if not history_path.exists():
        raise FileNotFoundError(f"Missing history file: {history_path}")
    history_markdown = history_path.read_text(encoding="utf-8")

    log("Loaded latest analysis JSON, summary markdown, history, and run metadata")
    return {
        "metadata": metadata,
        "analysis": analysis,
        "summary_markdown": summary_markdown,
        "history_markdown": history_markdown,
    }


def _extract_history_links(history_markdown: str) -> str:
    lines = []
    for raw in history_markdown.splitlines():
        stripped = raw.strip()
        if stripped.startswith("- [") and "](" in stripped:
            lines.append(stripped)
    return "\n".join(lines) if lines else "- No historical reports yet."


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "unknown-partner"


def _extract_partner(opportunity: dict[str, Any]) -> str:
    partner_keys = ("partner", "partner_name", "organization", "org", "company", "client")
    for key in partner_keys:
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return "Unspecified Partner"


def _extract_theme(opportunity: dict[str, Any]) -> str:
    raw_theme = opportunity.get("cluster_label") or opportunity.get("theme") or opportunity.get("category")
    if isinstance(raw_theme, str) and raw_theme.strip():
        return raw_theme.strip()

    tags = opportunity.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.strip():
                return tag.strip()

    return "Uncategorized"


def _build_ranked_opportunities(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = analysis.get("ranked_opportunities")
    if isinstance(ranked, list):
        valid = [item for item in ranked if isinstance(item, dict)]
        if valid:
            return valid

    flattened: list[dict[str, Any]] = []
    clusters = analysis.get("clusters") if isinstance(analysis.get("clusters"), list) else []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        opportunities = cluster.get("opportunities") if isinstance(cluster.get("opportunities"), list) else []
        for opportunity in opportunities:
            if not isinstance(opportunity, dict):
                continue
            flattened.append(opportunity)

    flattened.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)
    return flattened


def _build_themes_section(analysis: dict[str, Any]) -> str:
    clusters = analysis.get("clusters") if isinstance(analysis.get("clusters"), list) else []
    if not clusters:
        return "- No cluster themes found in the latest analysis."

    lines: list[str] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        label = str(cluster.get("label") or f"Cluster {cluster.get('id', '?')}")
        lines.append(f"- **{label}**")

        opportunities = cluster.get("opportunities") if isinstance(cluster.get("opportunities"), list) else []
        valid = [opp for opp in opportunities if isinstance(opp, dict)]
        valid.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)

        for opportunity in valid[:2]:
            title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
            score = _safe_float(opportunity.get("score"))
            lines.append(f"  - {title} (score: {score:.2f})")

    return "\n".join(lines) if lines else "- No cluster themes found in the latest analysis."


def _build_filter_controls(ranked_opportunities: list[dict[str, Any]]) -> str:
    themes = sorted({_extract_theme(opportunity) for opportunity in ranked_opportunities})
    partners = sorted({_extract_partner(opportunity) for opportunity in ranked_opportunities})

    theme_options = ["<option value=\"all\">All themes</option>"]
    theme_options.extend(
        f"<option value=\"{html.escape(theme)}\">{html.escape(theme)}</option>" for theme in themes
    )

    partner_options = ["<option value=\"all\">All partners</option>"]
    partner_options.extend(
        f"<option value=\"{html.escape(partner)}\">{html.escape(partner)}</option>" for partner in partners
    )

    return "\n".join(
        [
            "<div class=\"dashboard-filters\">",
            "  <h2>Filters</h2>",
            "  <label for=\"theme-filter\">Theme</label>",
            "  <select id=\"theme-filter\">",
            *[f"    {line}" for line in theme_options],
            "  </select>",
            "  <label for=\"score-filter\">Minimum score: <span id=\"score-filter-value\">0.00</span></label>",
            "  <input id=\"score-filter\" type=\"range\" min=\"0\" max=\"1\" step=\"0.01\" value=\"0\" />",
            "  <label for=\"partner-filter\">Partner</label>",
            "  <select id=\"partner-filter\">",
            *[f"    {line}" for line in partner_options],
            "  </select>",
            "  <p>Showing <strong id=\"visible-count\">0</strong> of <strong id=\"total-count\">0</strong> opportunities</p>",
            "</div>",
        ]
    )


def _build_opportunity_cards(ranked_opportunities: list[dict[str, Any]], run_id: str) -> str:
    if not ranked_opportunities:
        return "- No ranked opportunities available."

    lines: list[str] = ["<div id=\"opportunity-list\">"]

    for opportunity in ranked_opportunities:
        title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
        score = _safe_float(opportunity.get("score"))
        summary = str(opportunity.get("summary") or "")
        theme = _extract_theme(opportunity)
        partner = _extract_partner(opportunity)

        lines.extend(
            [
                (
                    f"  <article class=\"opportunity-card\" "
                    f"data-theme=\"{html.escape(theme)}\" "
                    f"data-score=\"{score:.4f}\" "
                    f"data-partner=\"{html.escape(partner)}\" "
                    f"data-run=\"{html.escape(run_id)}\">"
                ),
                f"    <h3>{html.escape(title)}</h3>",
                (
                    "    <p><strong>Score:</strong> "
                    f"{score:.2f} | <strong>Theme:</strong> {html.escape(theme)} "
                    f"| <strong>Partner:</strong> {html.escape(partner)}</p>"
                ),
            ]
        )

        if summary:
            lines.append(f"    <p>{html.escape(summary)}</p>")

        lines.append("  </article>")

    lines.append("</div>")
    return "\n".join(lines)


def _format_delta_line(label: str, payload: dict[str, Any], *, precision: int = 2) -> str:
    current = float(payload.get("current") or 0.0)
    previous = float(payload.get("previous") or 0.0)
    delta = float(payload.get("delta") or 0.0)
    sign = "+" if delta > 0 else ""
    return (
        f"- **{label}**: {current:.{precision}f} "
        f"(prev: {previous:.{precision}f}, Δ: {sign}{delta:.{precision}f})"
    )


def _build_weekly_deltas_section(trend_data: dict[str, Any]) -> str:
    deltas = trend_data.get("deltas") if isinstance(trend_data.get("deltas"), dict) else {}
    average_score = deltas.get("average_score") if isinstance(deltas.get("average_score"), dict) else {}
    theme_count = deltas.get("theme_count") if isinstance(deltas.get("theme_count"), dict) else {}

    if not average_score and not theme_count:
        return "- Not enough historical runs for week-over-week deltas yet."

    lines = []
    if average_score:
        lines.append(_format_delta_line("Average opportunity score", average_score, precision=2))
    if theme_count:
        lines.append(_format_delta_line("Theme count", theme_count, precision=0))
    return "\n".join(lines)


def _build_theme_delta_list(trend_data: dict[str, Any], key: str, empty_message: str) -> str:
    deltas = trend_data.get("deltas") if isinstance(trend_data.get("deltas"), dict) else {}
    entries = deltas.get(key) if isinstance(deltas.get(key), list) else []
    if not entries:
        return f"- {empty_message}"

    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        theme = str(entry.get("theme") or "Uncategorized")
        delta = int(entry.get("delta") or 0)
        sign = "+" if delta > 0 else ""
        lines.append(f"- {theme} ({sign}{delta})")
    return "\n".join(lines) if lines else f"- {empty_message}"


def _build_partner_themes(opportunities: list[dict[str, Any]]) -> str:
    theme_counts = Counter(_extract_theme(opportunity) for opportunity in opportunities)
    if not theme_counts:
        return "- No themes available for this partner."

    lines = [f"- {theme} ({count})" for theme, count in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))]
    return "\n".join(lines)


def _build_partner_links(partner_pages: list[tuple[str, str]]) -> str:
    if not partner_pages:
        return "## Partner Dashboards\n\n- No partner dashboards available."

    lines = ["## Partner Dashboards", ""]
    for partner_name, file_name in partner_pages:
        lines.append(f"- [{partner_name}](partners/{file_name})")
    return "\n".join(lines)


def _humanize_slug(slug: str) -> str:
    text = slug.replace("-", " ").strip()
    return text.title() if text else "Untitled Theme"


def _extract_markdown_heading(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                heading = stripped[2:].strip()
                if heading.lower().endswith(" dashboard"):
                    heading = heading[: -len(" dashboard")].strip()
                return heading or None
    except Exception:
        return None
    return None


def _collect_theme_pages(themes_dir: Path) -> list[tuple[str, str, str]]:
    if not themes_dir.exists():
        return []

    pages: list[tuple[str, str, str]] = []
    for path in sorted(themes_dir.glob("*.md")):
        slug = path.stem
        label = _extract_markdown_heading(path) or _humanize_slug(slug)
        pages.append((label, path.name, slug))
    return pages


def _build_theme_links(theme_pages: list[tuple[str, str, str]], docs_dir: Path) -> str:
    if not theme_pages:
        return "## Browse by Theme\n\n- No theme dashboards available."

    lines = ["## Browse by Theme", ""]
    for label, file_name, slug in theme_pages:
        lines.append(f"- [{label}](themes/{file_name})")
        thumbnail_path = docs_dir / "charts" / "themes" / f"{slug}_opportunity_count_trend.png"
        if thumbnail_path.exists():
            lines.append(
                f"  <br><img src=\"charts/themes/{slug}_opportunity_count_trend.png\" width=\"220\" alt=\"{html.escape(label)} trend thumbnail\" />"
            )
    return "\n".join(lines)


def _build_navigation_links(
    *,
    partner_pages: list[tuple[str, str]],
    theme_pages: list[tuple[str, str, str]],
    docs_dir: Path,
) -> str:
    theme_links = _build_theme_links(theme_pages, docs_dir=docs_dir)
    partner_links = _build_partner_links(partner_pages)
    return f"{theme_links}\n\n{partner_links}"


def _build_comparative_insights_section(docs_dir: Path) -> str:
    comparative_path = docs_dir / "comparative.md"
    if not comparative_path.exists():
        return ""

    lines = [
        "## Cross-Partner × Cross-Theme Insights",
        "",
        "- [Open comparative analytics](comparative.md)",
    ]

    preview_path = docs_dir / "charts" / "comparative" / "partner_theme_heatmap.png"
    if preview_path.exists():
        lines.extend(
            [
                "",
                '<img src="charts/comparative/partner_theme_heatmap.png" width="700" alt="Partner by theme heatmap preview" />',
            ]
        )

    return "\n".join(lines)


def _render_partner_dashboards(
    *,
    analysis: dict[str, Any],
    history_markdown: str,
    docs_dir: Path,
    partner_template_path: Path,
    partners_dir: Path,
    run_id: str,
    trend_charts_markdown: str,
) -> list[tuple[str, str]]:
    if not partner_template_path.exists():
        raise FileNotFoundError(f"Missing partner template: {partner_template_path}")

    partner_template_text = partner_template_path.read_text(encoding="utf-8")
    ranked_opportunities = _build_ranked_opportunities(analysis)
    opportunities_by_partner: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for opportunity in ranked_opportunities:
        opportunities_by_partner[_extract_partner(opportunity)].append(opportunity)

    partners_dir.mkdir(parents=True, exist_ok=True)
    for existing_file in partners_dir.glob("*.md"):
        existing_file.unlink()

    trends_section = trend_charts_markdown or "- No trend charts available."
    history_links = _extract_history_links(history_markdown)

    used_slugs: set[str] = set()
    rendered_pages: list[tuple[str, str]] = []

    for partner_name in sorted(opportunities_by_partner.keys()):
        opportunities = opportunities_by_partner[partner_name]
        opportunities.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)

        base_slug = _slugify(partner_name)
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)

        file_name = f"{slug}.md"
        partner_path = partners_dir / file_name

        replacements = {
            "{{partner_name}}": partner_name,
            "{{partner_themes}}": _build_partner_themes(opportunities),
            "{{partner_opportunities}}": _build_opportunity_cards(opportunities, run_id),
            "{{partner_trends}}": trends_section,
            "{{partner_history_links}}": history_links,
        }

        rendered = partner_template_text
        for placeholder, value in replacements.items():
            rendered = rendered.replace(placeholder, value)

        partner_path.write_text(rendered.rstrip() + "\n", encoding="utf-8")
        rendered_pages.append((partner_name, file_name))

    return rendered_pages


def fill_template_placeholders(
    template_text: str,
    inputs: dict[str, Any],
    partner_links: str,
    trend_data: dict[str, Any],
    trend_charts_markdown: str,
    docs_dir: Path = Path("docs"),
) -> str:
    log("Filling dashboard template placeholders")

    metadata = inputs["metadata"]
    analysis = inputs["analysis"]
    run_id = str(metadata.get("run_id") or analysis.get("run_id") or "")
    ranked_opportunities = _build_ranked_opportunities(analysis)

    timestamp = str(metadata.get("generated_utc") or analysis.get("generated_utc") or "")
    themes_section = _build_themes_section(analysis)
    opportunities_section = _build_opportunity_cards(ranked_opportunities, run_id)
    full_summary = str(inputs["summary_markdown"]).strip()
    history_links = _extract_history_links(str(inputs["history_markdown"]))
    filter_controls = _build_filter_controls(ranked_opportunities)
    weekly_deltas = _build_weekly_deltas_section(trend_data)
    rising_themes = _build_theme_delta_list(
        trend_data,
        key="top_rising_themes",
        empty_message="No rising themes this week.",
    )
    falling_themes = _build_theme_delta_list(
        trend_data,
        key="top_falling_themes",
        empty_message="No falling themes this week.",
    )

    replacements = {
        "{{timestamp}}": timestamp,
        "{{partner_links}}": partner_links,
        "{{filter_controls}}": filter_controls,
        "{{themes_section}}": themes_section,
        "{{opportunities_section}}": opportunities_section,
        "{{weekly_trend_charts}}": trend_charts_markdown,
        "{{weekly_deltas}}": weekly_deltas,
        "{{rising_themes}}": rising_themes,
        "{{falling_themes}}": falling_themes,
        "{{full_summary}}": full_summary,
        "{{history_links}}": history_links,
    }

    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)

    comparative_section = _build_comparative_insights_section(docs_dir=docs_dir)
    if comparative_section:
        marker = "\n## Full Summary"
        if marker in rendered:
            rendered = rendered.replace(marker, f"\n{comparative_section}\n\n## Full Summary", 1)
        else:
            rendered = rendered.rstrip() + f"\n\n{comparative_section}\n"

    return rendered.rstrip() + "\n"


def write_rendered_dashboard(rendered_markdown: str, output_path: Path = Path("docs/index.md")) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_markdown, encoding="utf-8")
    log(f"Wrote rendered dashboard to {output_path}")
    return output_path


def render_dashboard(
    template_path: Path = Path("docs/dashboard_template.md"),
    partner_template_path: Path = Path("docs/partner_template.md"),
    analyses_dir: Path = Path("analyses"),
    docs_dir: Path = Path("docs"),
    metadata_path: Path = Path("run_metadata.json"),
    trend_data_path: Path | None = None,
    partners_dir: Path = Path("docs/partners"),
    output_path: Path = Path("docs/index.md"),
) -> Path:
    log("Starting dashboard rendering")
    if not template_path.exists():
        raise FileNotFoundError(f"Missing dashboard template: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")
    inputs = load_dashboard_inputs(analyses_dir=analyses_dir, docs_dir=docs_dir, metadata_path=metadata_path)
    metadata = inputs["metadata"]
    analysis = inputs["analysis"]
    run_id = str(metadata.get("run_id") or analysis.get("run_id") or "")

    if trend_data_path and trend_data_path.exists():
        trend_data = _load_json(trend_data_path)
        log(f"Loaded precomputed trend data from {trend_data_path}")
    else:
        trend_data = build_trend_data(analyses_dir=analyses_dir)

    trend_charts_markdown = generate_trend_charts(
        trend_data=trend_data,
        charts_dir=docs_dir / "charts",
    )

    partner_pages = _render_partner_dashboards(
        analysis=analysis,
        history_markdown=str(inputs["history_markdown"]),
        docs_dir=docs_dir,
        partner_template_path=partner_template_path,
        partners_dir=partners_dir,
        run_id=run_id,
        trend_charts_markdown=trend_charts_markdown,
    )
    theme_pages = _collect_theme_pages(docs_dir / "themes")
    partner_links = _build_navigation_links(
        partner_pages=partner_pages,
        theme_pages=theme_pages,
        docs_dir=docs_dir,
    )

    rendered = fill_template_placeholders(
        template_text,
        inputs,
        partner_links=partner_links,
        trend_data=trend_data,
        trend_charts_markdown=trend_charts_markdown,
        docs_dir=docs_dir,
    )
    return write_rendered_dashboard(rendered, output_path=output_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render docs/index.md from dashboard template and latest artifacts")
    parser.add_argument("--template", default="docs/dashboard_template.md", help="Path to dashboard template markdown")
    parser.add_argument("--partner-template", default="docs/partner_template.md", help="Path to partner template markdown")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing weekly analysis JSON files")
    parser.add_argument("--docs-dir", default="docs", help="Directory containing docs files")
    parser.add_argument("--metadata", default="run_metadata.json", help="Path to run metadata JSON")
    parser.add_argument("--trend-data", default="", help="Optional path to precomputed trend data JSON")
    parser.add_argument("--partners-dir", default="docs/partners", help="Output directory for partner markdown pages")
    parser.add_argument("--output", default="docs/index.md", help="Output path for rendered dashboard markdown")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    render_dashboard(
        template_path=Path(args.template),
        partner_template_path=Path(args.partner_template),
        analyses_dir=Path(args.analyses_dir),
        docs_dir=Path(args.docs_dir),
        metadata_path=Path(args.metadata),
        trend_data_path=Path(args.trend_data) if args.trend_data else None,
        partners_dir=Path(args.partners_dir),
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
