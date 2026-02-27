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


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _format_axis_label(label: str, limit: int = 26) -> str:
    text = str(label or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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


def generate_theme_opportunity_count_trend_chart(
    *,
    theme_slug: str,
    theme_label: str,
    run_points: list[dict[str, Any]],
    charts_dir: Path = Path("docs/charts/themes"),
    image_prefix: str = "../charts/themes",
) -> str:
    if not run_points:
        log(f"No run points for theme '{theme_label}'; skipping opportunity count chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping theme opportunity count chart: {exc}")
        return ""

    labels = [str(point.get("run_id") or "unknown") for point in run_points]
    values = [int(point.get("opportunity_count") or 0) for point in run_points]

    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(labels, values, marker="o")
    ax.set_title(f"{theme_label}: Opportunity Count Trend")
    ax.set_xlabel("Run")
    ax.set_ylabel("Opportunity Count")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / f"{theme_slug}_opportunity_count_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, f"{theme_label} Opportunity Count Trend")


def generate_theme_average_score_trend_chart(
    *,
    theme_slug: str,
    theme_label: str,
    run_points: list[dict[str, Any]],
    charts_dir: Path = Path("docs/charts/themes"),
    image_prefix: str = "../charts/themes",
) -> str:
    if not run_points:
        log(f"No run points for theme '{theme_label}'; skipping average score chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping theme average score chart: {exc}")
        return ""

    labels = [str(point.get("run_id") or "unknown") for point in run_points]
    values = [float(point.get("average_score") or 0.0) for point in run_points]

    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(labels, values, marker="o")
    ax.set_title(f"{theme_label}: Average Score Trend")
    ax.set_xlabel("Run")
    ax.set_ylabel("Average Score")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / f"{theme_slug}_average_score_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, f"{theme_label} Average Score Trend")


def generate_partner_by_theme_stacked_bar_chart(
    *,
    theme_slug: str,
    theme_label: str,
    run_points: list[dict[str, Any]],
    charts_dir: Path = Path("docs/charts/themes"),
    image_prefix: str = "../charts/themes",
    max_partners: int = 6,
) -> str:
    if not run_points:
        log(f"No run points for theme '{theme_label}'; skipping partner-by-theme chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping partner-by-theme chart: {exc}")
        return ""

    partner_totals: dict[str, int] = {}
    for point in run_points:
        partner_counts = point.get("partner_counts") if isinstance(point.get("partner_counts"), dict) else {}
        for partner, count in partner_counts.items():
            partner_name = str(partner)
            partner_totals[partner_name] = partner_totals.get(partner_name, 0) + int(count or 0)

    if not partner_totals:
        log(f"No partner counts for theme '{theme_label}'; skipping partner-by-theme chart")
        return ""

    selected_partners = [
        partner for partner, _ in sorted(partner_totals.items(), key=lambda item: (-item[1], item[0]))[:max_partners]
    ]
    labels = [str(point.get("run_id") or "unknown") for point in run_points]

    fig = plt.figure(figsize=(11, 4.5))
    ax = fig.add_subplot(1, 1, 1)
    bottoms = [0] * len(run_points)

    for partner in selected_partners:
        values = []
        for point in run_points:
            partner_counts = point.get("partner_counts") if isinstance(point.get("partner_counts"), dict) else {}
            values.append(int(partner_counts.get(partner, 0) or 0))
        ax.bar(labels, values, bottom=bottoms, label=partner)
        bottoms = [bottoms[index] + values[index] for index in range(len(values))]

    ax.set_title(f"{theme_label}: Partner Mix by Run")
    ax.set_xlabel("Run")
    ax.set_ylabel("Opportunity Count")
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)

    output_path = charts_dir / f"{theme_slug}_partner_mix_trend.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, f"{theme_label} Partner Mix Trend")


def generate_partner_theme_heatmap(
    comparative_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    matrix = comparative_data.get("matrix") if isinstance(comparative_data.get("matrix"), dict) else {}
    counts = matrix.get("counts") if isinstance(matrix.get("counts"), dict) else {}
    partners = comparative_data.get("partners") if isinstance(comparative_data.get("partners"), list) else []
    themes = comparative_data.get("themes") if isinstance(comparative_data.get("themes"), list) else []

    valid_partners = [str(partner) for partner in partners if isinstance(partner, str)]
    valid_themes = [str(theme) for theme in themes if isinstance(theme, str)]
    if not valid_partners or not valid_themes:
        log("Insufficient comparative data for partner x theme heatmap")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping comparative heatmap: {exc}")
        return ""

    values: list[list[int]] = []
    for partner in valid_partners:
        row_counts = counts.get(partner) if isinstance(counts.get(partner), dict) else {}
        row = [int(row_counts.get(theme, 0) or 0) for theme in valid_themes]
        values.append(row)

    fig = plt.figure(figsize=(max(8, len(valid_themes) * 1.1), max(4.5, len(valid_partners) * 0.6)))
    ax = fig.add_subplot(1, 1, 1)
    image = ax.imshow(values, cmap="YlGnBu", aspect="auto")
    fig.colorbar(image, ax=ax, label="Opportunity Count")

    ax.set_title("Partner × Theme Opportunity Heatmap")
    ax.set_xticks(range(len(valid_themes)))
    ax.set_xticklabels([_format_axis_label(theme) for theme in valid_themes], rotation=45, ha="right")
    ax.set_yticks(range(len(valid_partners)))
    ax.set_yticklabels([_format_axis_label(partner) for partner in valid_partners])

    output_path = charts_dir / "partner_theme_heatmap.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, "Partner x Theme Heatmap")


def generate_partner_specialization_bar_chart(
    comparative_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    strengths = (
        comparative_data.get("partner_strengths") if isinstance(comparative_data.get("partner_strengths"), list) else []
    )
    if not strengths:
        log("No partner strengths found; skipping specialization chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping partner specialization chart: {exc}")
        return ""

    labels: list[str] = []
    values: list[int] = []
    for entry in strengths:
        if not isinstance(entry, dict):
            continue
        partner = str(entry.get("partner") or "")
        strong_themes = entry.get("strong_themes") if isinstance(entry.get("strong_themes"), list) else []
        if not partner:
            continue
        labels.append(_format_axis_label(partner, limit=22))
        values.append(len(strong_themes))

    if not labels:
        return ""

    fig = plt.figure(figsize=(max(8, len(labels) * 0.85), 4.5))
    ax = fig.add_subplot(1, 1, 1)
    ax.bar(labels, values)
    ax.set_title("Partner Specialization (Strong Themes Count)")
    ax.set_xlabel("Partner")
    ax.set_ylabel("Strong Themes")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / "partner_specialization.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, "Partner Specialization")


def generate_theme_coverage_chart(
    comparative_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    matrix = comparative_data.get("matrix") if isinstance(comparative_data.get("matrix"), dict) else {}
    counts = matrix.get("counts") if isinstance(matrix.get("counts"), dict) else {}
    themes = comparative_data.get("themes") if isinstance(comparative_data.get("themes"), list) else []
    partners = comparative_data.get("partners") if isinstance(comparative_data.get("partners"), list) else []

    valid_themes = [str(theme) for theme in themes if isinstance(theme, str)]
    valid_partners = [str(partner) for partner in partners if isinstance(partner, str)]
    if not valid_themes or not valid_partners:
        log("Insufficient comparative data for theme coverage chart")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping theme coverage chart: {exc}")
        return ""

    labels: list[str] = []
    values: list[int] = []
    for theme in valid_themes:
        coverage = 0
        for partner in valid_partners:
            partner_counts = counts.get(partner) if isinstance(counts.get(partner), dict) else {}
            if int(partner_counts.get(theme, 0) or 0) > 0:
                coverage += 1
        labels.append(_format_axis_label(theme, limit=24))
        values.append(coverage)

    fig = plt.figure(figsize=(max(8, len(labels) * 0.85), 4.5))
    ax = fig.add_subplot(1, 1, 1)
    ax.bar(labels, values)
    ax.set_title("Theme Coverage Across Partners")
    ax.set_xlabel("Theme")
    ax.set_ylabel("Partners with Activity")
    ax.tick_params(axis="x", labelrotation=45)

    output_path = charts_dir / "theme_coverage.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, "Theme Coverage")


def generate_delta_heatmap(
    comparative_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    matrix = comparative_data.get("matrix") if isinstance(comparative_data.get("matrix"), dict) else {}
    delta_counts = matrix.get("delta_counts") if isinstance(matrix.get("delta_counts"), dict) else {}
    partners = comparative_data.get("partners") if isinstance(comparative_data.get("partners"), list) else []
    themes = comparative_data.get("themes") if isinstance(comparative_data.get("themes"), list) else []

    valid_partners = [str(partner) for partner in partners if isinstance(partner, str)]
    valid_themes = [str(theme) for theme in themes if isinstance(theme, str)]
    if not valid_partners or not valid_themes:
        log("Insufficient comparative data for delta heatmap")
        return ""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log(f"matplotlib not available; skipping delta heatmap: {exc}")
        return ""

    values: list[list[int]] = []
    for partner in valid_partners:
        partner_deltas = delta_counts.get(partner) if isinstance(delta_counts.get(partner), dict) else {}
        row = [int(partner_deltas.get(theme, 0) or 0) for theme in valid_themes]
        values.append(row)

    max_abs = max(abs(value) for row in values for value in row) if values else 1
    if max_abs == 0:
        max_abs = 1

    fig = plt.figure(figsize=(max(8, len(valid_themes) * 1.1), max(4.5, len(valid_partners) * 0.6)))
    ax = fig.add_subplot(1, 1, 1)
    image = ax.imshow(values, cmap="RdYlGn", aspect="auto", vmin=-max_abs, vmax=max_abs)
    fig.colorbar(image, ax=ax, label="Week-over-Week Delta")

    ax.set_title("Partner × Theme Week-over-Week Delta Heatmap")
    ax.set_xticks(range(len(valid_themes)))
    ax.set_xticklabels([_format_axis_label(theme) for theme in valid_themes], rotation=45, ha="right")
    ax.set_yticks(range(len(valid_partners)))
    ax.set_yticklabels([_format_axis_label(partner) for partner in valid_partners])

    output_path = charts_dir / "partner_theme_delta_heatmap.png"
    _save_chart(fig, output_path)
    plt.close(fig)
    return _to_markdown_image(Path(image_prefix) / output_path.name, "Partner x Theme Delta Heatmap")


def generate_comparative_charts(
    comparative_data: dict[str, Any],
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    charts = [
        generate_partner_theme_heatmap(
            comparative_data=comparative_data,
            charts_dir=charts_dir,
            image_prefix=image_prefix,
        ),
        generate_delta_heatmap(
            comparative_data=comparative_data,
            charts_dir=charts_dir,
            image_prefix=image_prefix,
        ),
        generate_partner_specialization_bar_chart(
            comparative_data=comparative_data,
            charts_dir=charts_dir,
            image_prefix=image_prefix,
        ),
        generate_theme_coverage_chart(
            comparative_data=comparative_data,
            charts_dir=charts_dir,
            image_prefix=image_prefix,
        ),
    ]
    valid = [chart for chart in charts if chart]
    return "\n\n".join(valid)


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


def generate_comparative_chart_markdown(
    comparative_data_path: Path,
    charts_dir: Path = Path("docs/charts/comparative"),
    image_prefix: str = "charts/comparative",
) -> str:
    if not comparative_data_path.exists():
        log(f"Comparative data file not found: {comparative_data_path}")
        return ""

    comparative_data = _load_json(comparative_data_path)
    markdown = generate_comparative_charts(
        comparative_data=comparative_data,
        charts_dir=charts_dir,
        image_prefix=image_prefix,
    )
    if markdown:
        log("Generated comparative chart markdown for embedding")
    else:
        log("No comparative chart markdown generated")
    return markdown


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate trend charts from historical analyses")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing analysis JSON files")
    parser.add_argument("--charts-dir", default="docs/charts", help="Directory to write generated PNG charts")
    parser.add_argument("--trend-data", default="", help="Optional precomputed trend data JSON path")
    parser.add_argument("--comparative-data", default="", help="Optional comparative data JSON path")
    parser.add_argument(
        "--comparative-charts-dir",
        default="docs/charts/comparative",
        help="Directory to write comparative PNG charts",
    )
    parser.add_argument(
        "--comparative-markdown-output",
        default="",
        help="Optional path to write comparative chart markdown",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    trend_markdown = generate_chart_markdown(
        analyses_dir=Path(args.analyses_dir),
        charts_dir=Path(args.charts_dir),
        trend_data_path=Path(args.trend_data) if args.trend_data else None,
    )
    if trend_markdown:
        print(trend_markdown)

    if args.comparative_data:
        comparative_markdown = generate_comparative_chart_markdown(
            comparative_data_path=Path(args.comparative_data),
            charts_dir=Path(args.comparative_charts_dir),
            image_prefix="charts/comparative",
        )
        if comparative_markdown:
            print(comparative_markdown)

        if args.comparative_markdown_output:
            output_path = Path(args.comparative_markdown_output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text((comparative_markdown or "").rstrip() + "\n", encoding="utf-8")
            log(f"Wrote comparative chart markdown to {output_path}")


if __name__ == "__main__":
    main()
