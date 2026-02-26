#!/usr/bin/env python3
"""Optional chart generation for dashboard trend visualization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from log_utils import log


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_historical_analyses(analyses_dir: Path = Path("analyses")) -> list[dict[str, Any]]:
    log(f"Loading historical analyses from {analyses_dir}")
    files = sorted(analyses_dir.glob("weekly-*.json"), key=lambda p: p.name)
    analyses = []
    for file_path in files:
        try:
            analyses.append(_load_json(file_path))
        except Exception as exc:
            log(f"Skipping unreadable analysis file {file_path}: {exc}")
    log(f"Loaded {len(analyses)} historical analysis files")
    return analyses


def _extract_run_label(analysis: dict[str, Any]) -> str:
    run_id = str(analysis.get("run_id") or "")
    if run_id.startswith("run-"):
        return run_id.replace("run-", "")
    return run_id or "unknown"


def _extract_average_score(analysis: dict[str, Any]) -> float:
    ranked = analysis.get("ranked_opportunities") if isinstance(analysis.get("ranked_opportunities"), list) else []
    scores = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        scores.append(float(item.get("score") or 0.0))
    if scores:
        return sum(scores) / len(scores)

    clusters = analysis.get("clusters") if isinstance(analysis.get("clusters"), list) else []
    cluster_scores = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        opportunities = cluster.get("opportunities") if isinstance(cluster.get("opportunities"), list) else []
        for opportunity in opportunities:
            if isinstance(opportunity, dict):
                cluster_scores.append(float(opportunity.get("score") or 0.0))
    return (sum(cluster_scores) / len(cluster_scores)) if cluster_scores else 0.0


def generate_charts(
    analyses: list[dict[str, Any]],
    charts_dir: Path = Path("docs/charts"),
) -> str:
    if not analyses:
        log("No historical data exists; skipping chart generation")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping chart generation: {exc}")
        return ""

    charts_dir.mkdir(parents=True, exist_ok=True)
    log(f"Generating charts into {charts_dir}")

    labels = [_extract_run_label(analysis) for analysis in analyses]
    rows_analyzed = [int(analysis.get("rows_analyzed") or 0) for analysis in analyses]
    avg_scores = [_extract_average_score(analysis) for analysis in analyses]

    paths: list[Path] = []

    plt.figure(figsize=(10, 4))
    plt.plot(labels, rows_analyzed, marker="o")
    plt.title("Rows Analyzed per Run")
    plt.xlabel("Run")
    plt.ylabel("Rows Analyzed")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    rows_path = charts_dir / "rows_analyzed_trend.png"
    plt.savefig(rows_path, dpi=120)
    plt.close()
    paths.append(rows_path)

    plt.figure(figsize=(10, 4))
    plt.plot(labels, avg_scores, marker="o")
    plt.title("Average Opportunity Score per Run")
    plt.xlabel("Run")
    plt.ylabel("Average Score")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    avg_path = charts_dir / "avg_opportunity_score_trend.png"
    plt.savefig(avg_path, dpi=120)
    plt.close()
    paths.append(avg_path)

    markdown = "\n\n".join(f"![{path.stem}]({path.as_posix()})" for path in paths)
    log(f"Generated {len(paths)} chart(s)")
    return markdown


def generate_chart_markdown(
    analyses_dir: Path = Path("analyses"),
    charts_dir: Path = Path("docs/charts"),
) -> str:
    analyses = load_historical_analyses(analyses_dir=analyses_dir)
    return generate_charts(analyses=analyses, charts_dir=charts_dir)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate optional dashboard charts from historical analyses")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing weekly analysis JSON files")
    parser.add_argument("--charts-dir", default="docs/charts", help="Directory to write generated PNG charts")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    markdown = generate_chart_markdown(
        analyses_dir=Path(args.analyses_dir),
        charts_dir=Path(args.charts_dir),
    )
    if markdown:
        log("Chart markdown generated for embedding")
    else:
        log("No chart markdown generated")


if __name__ == "__main__":
    main()
