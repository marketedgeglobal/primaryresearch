#!/usr/bin/env python3
"""Render the GitHub Pages dashboard from template and latest outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from log_utils import log


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

    flattened.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
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
        valid.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

        for opportunity in valid[:2]:
            title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
            score = float(opportunity.get("score") or 0.0)
            lines.append(f"  - {title} (score: {score:.2f})")

    return "\n".join(lines) if lines else "- No cluster themes found in the latest analysis."


def _build_opportunities_section(analysis: dict[str, Any], max_items: int = 10) -> str:
    ranked = _build_ranked_opportunities(analysis)
    if not ranked:
        return "- No ranked opportunities available."

    lines: list[str] = []
    for idx, opportunity in enumerate(ranked[:max_items], start=1):
        title = str(opportunity.get("title") or opportunity.get("name") or "Untitled")
        score = float(opportunity.get("score") or 0.0)
        summary = str(opportunity.get("summary") or "")
        lines.append(f"{idx}. **{title}** — score: {score:.2f}")
        if summary:
            lines.append(f"   - {summary}")
    return "\n".join(lines)


def _build_trends_section(docs_dir: Path) -> str:
    charts_dir = docs_dir / "charts"
    if not charts_dir.exists():
        return ""

    chart_files = sorted(charts_dir.glob("*.png"))
    if not chart_files:
        return ""

    lines = [f"![{chart.stem}]({chart.as_posix()})" for chart in chart_files]
    return "\n\n".join(lines)


def fill_template_placeholders(template_text: str, inputs: dict[str, Any], docs_dir: Path = Path("docs")) -> str:
    log("Filling dashboard template placeholders")

    metadata = inputs["metadata"]
    analysis = inputs["analysis"]

    timestamp = str(metadata.get("generated_utc") or analysis.get("generated_utc") or "")
    themes_section = _build_themes_section(analysis)
    opportunities_section = _build_opportunities_section(analysis)
    trends_section = _build_trends_section(docs_dir)
    full_summary = str(inputs["summary_markdown"]).strip()
    history_links = _extract_history_links(str(inputs["history_markdown"]))

    replacements = {
        "{{timestamp}}": timestamp,
        "{{themes_section}}": themes_section,
        "{{opportunities_section}}": opportunities_section,
        "{{trends_section}}": trends_section,
        "{{full_summary}}": full_summary,
        "{{history_links}}": history_links,
    }

    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered.rstrip() + "\n"


def write_rendered_dashboard(rendered_markdown: str, output_path: Path = Path("docs/index.md")) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_markdown, encoding="utf-8")
    log(f"Wrote rendered dashboard to {output_path}")
    return output_path


def render_dashboard(
    template_path: Path = Path("docs/dashboard_template.md"),
    analyses_dir: Path = Path("analyses"),
    docs_dir: Path = Path("docs"),
    metadata_path: Path = Path("run_metadata.json"),
    output_path: Path = Path("docs/index.md"),
) -> Path:
    log("Starting dashboard rendering")
    if not template_path.exists():
        raise FileNotFoundError(f"Missing dashboard template: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")
    inputs = load_dashboard_inputs(analyses_dir=analyses_dir, docs_dir=docs_dir, metadata_path=metadata_path)
    rendered = fill_template_placeholders(template_text, inputs, docs_dir=docs_dir)
    return write_rendered_dashboard(rendered, output_path=output_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render docs/index.md from dashboard template and latest artifacts")
    parser.add_argument("--template", default="docs/dashboard_template.md", help="Path to dashboard template markdown")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing weekly analysis JSON files")
    parser.add_argument("--docs-dir", default="docs", help="Directory containing docs files")
    parser.add_argument("--metadata", default="run_metadata.json", help="Path to run metadata JSON")
    parser.add_argument("--output", default="docs/index.md", help="Output path for rendered dashboard markdown")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    render_dashboard(
        template_path=Path(args.template),
        analyses_dir=Path(args.analyses_dir),
        docs_dir=Path(args.docs_dir),
        metadata_path=Path(args.metadata),
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
