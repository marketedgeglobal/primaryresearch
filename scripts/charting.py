#!/usr/bin/env python3
"""Chart generation utilities for trend analytics visualizations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from log_utils import log
from trend_analysis import build_trend_data


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_labels(runs: list[dict[str, Any]]) -> list[str]:
    return [str(run.get("run_id") or "unknown") for run in runs]


def _to_markdown_image(path: Path, title: str) -> str:
    return f"![{title}]({path.as_posix()})"


def _save_chart(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    fig.clf()


def generate_score_trend_line_chart(
    trend_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts"),
) -> str:
    runs = trend_data.get("runs") if isinstance(trend_data.get("runs"), list) else []
    if not runs:
        log("No runs in trend data; skipping score trend chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping chart generation: {exc}")
        return ""

    labels = _extract_labels(runs)
    values = [float(run.get("average_score") or 0.0) for run in runs]

    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(labels, values, marker="o")
    ax.set_title("Average Opportunity Score Trend")
    ax.set_xlabel("Run")
    ax.set_ylabel("Average Score")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / "score_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(output_path, "Score Trend")


def generate_theme_count_line_chart(
    trend_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts"),
) -> str:
    runs = trend_data.get("runs") if isinstance(trend_data.get("runs"), list) else []
    if not runs:
        log("No runs in trend data; skipping theme count chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping theme count chart: {exc}")
        return ""

    labels = _extract_labels(runs)
    values = [int(run.get("theme_count") or 0) for run in runs]

    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(labels, values, marker="o")
    ax.set_title("Theme Count Trend")
    ax.set_xlabel("Run")
    ax.set_ylabel("Theme Count")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / "theme_count_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(output_path, "Theme Count Trend")


def generate_partner_stacked_bar_chart(
    trend_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts"),
    max_partners: int = 6,
) -> str:
    runs = trend_data.get("runs") if isinstance(trend_data.get("runs"), list) else []
    if not runs:
        log("No runs in trend data; skipping partner stacked bar chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping partner chart: {exc}")
        return ""

    partner_totals: dict[str, int] = {}
    for run in runs:
        partner_counts = run.get("per_partner_counts")
        if not isinstance(partner_counts, dict):
            continue
        for partner, count in partner_counts.items():
            partner_name = str(partner)
            partner_totals[partner_name] = partner_totals.get(partner_name, 0) + int(count or 0)

    if not partner_totals:
        log("No partner fields found in trend data; skipping partner stacked bar chart")
        return ""

    selected_partners = [
        partner for partner, _ in sorted(partner_totals.items(), key=lambda item: (-item[1], item[0]))[:max_partners]
    ]
    labels = _extract_labels(runs)

    fig = plt.figure(figsize=(11, 4.5))
    ax = fig.add_subplot(1, 1, 1)
    bottoms = [0] * len(runs)

    for partner in selected_partners:
        values = []
        for run in runs:
            partner_counts = run.get("per_partner_counts") if isinstance(run.get("per_partner_counts"), dict) else {}
            values.append(int(partner_counts.get(partner, 0) or 0))
        ax.bar(labels, values, bottom=bottoms, label=partner)
        bottoms = [bottoms[index] + values[index] for index in range(len(values))]

    ax.set_title("Partner Opportunity Mix by Run")
    ax.set_xlabel("Run")
    ax.set_ylabel("Opportunity Count")
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)

    output_path = charts_dir / "partner_stacked_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(output_path, "Partner Trend")


def generate_trend_charts(
    trend_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts"),
) -> str:
    charts = [
        generate_score_trend_line_chart(trend_data=trend_data, charts_dir=charts_dir),
        generate_theme_count_line_chart(trend_data=trend_data, charts_dir=charts_dir),
        generate_partner_stacked_bar_chart(trend_data=trend_data, charts_dir=charts_dir),
    ]
    valid = [chart for chart in charts if chart]
    return "\n\n".join(valid)


def generate_chart_markdown(
    analyses_dir: Path = Path("analyses"),
    charts_dir: Path = Path("docs/charts"),
    trend_data_path: Path | None = None,
) -> str:
    if trend_data_path and trend_data_path.exists():
        trend_data = _load_json(trend_data_path)
        log(f"Loaded trend data from {trend_data_path}")
    else:
        trend_data = build_trend_data(analyses_dir=analyses_dir)
    markdown = generate_trend_charts(trend_data=trend_data, charts_dir=charts_dir)
    if markdown:
        log("Generated trend chart markdown for embedding")
    else:
        log("No trend chart markdown generated")
    return markdown


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate trend charts from historical analyses")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing analysis JSON files")
    parser.add_argument("--charts-dir", default="docs/charts", help="Directory to write generated PNG charts")
    parser.add_argument("--trend-data", default="", help="Optional precomputed trend data JSON path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    markdown = generate_chart_markdown(
        analyses_dir=Path(args.analyses_dir),
        charts_dir=Path(args.charts_dir),
        trend_data_path=Path(args.trend_data) if args.trend_data else None,
    )
    if markdown:
        print(markdown)


if __name__ == "__main__":
    main()
