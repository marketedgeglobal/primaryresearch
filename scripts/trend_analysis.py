#!/usr/bin/env python3
"""Trend analytics across historical weekly analysis outputs."""

from __future__ import annotations

import argparse
import json
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


def _extract_partner(opportunity: dict[str, Any]) -> str | None:
    for key in ("partner", "partner_name", "organization", "org", "company", "client"):
        raw = opportunity.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


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


def build_trend_data(analyses_dir: Path = Path("analyses")) -> dict[str, Any]:
    run_records = load_analysis_runs(analyses_dir=analyses_dir)

    runs: list[dict[str, Any]] = []
    score_trend: list[dict[str, Any]] = []
    theme_trend: list[dict[str, Any]] = []
    partner_trend: list[dict[str, Any]] = []

    for record in run_records:
        payload = record["analysis"]
        run_id = record["run_id"]
        generated_utc = str(payload.get("generated_utc") or record["run_datetime"].isoformat())
        opportunities = _extract_opportunities(payload)

        scores = [_extract_score(opportunity) for opportunity in opportunities]
        average_score = (sum(scores) / len(scores)) if scores else 0.0

        per_theme_counts: dict[str, int] = {}
        per_partner_counts: dict[str, int] = {}
        for opportunity in opportunities:
            theme = _extract_theme(opportunity)
            per_theme_counts[theme] = per_theme_counts.get(theme, 0) + 1

            partner = _extract_partner(opportunity)
            if partner:
                per_partner_counts[partner] = per_partner_counts.get(partner, 0) + 1

        run_summary = {
            "run_id": run_id,
            "generated_utc": generated_utc,
            "average_score": round(average_score, 4),
            "opportunity_count": len(opportunities),
            "theme_count": len(per_theme_counts),
            "per_theme_counts": dict(sorted(per_theme_counts.items(), key=lambda item: item[0].lower())),
            "per_partner_counts": dict(sorted(per_partner_counts.items(), key=lambda item: item[0].lower())),
        }
        runs.append(run_summary)

        score_trend.append(
            {
                "run_id": run_id,
                "generated_utc": generated_utc,
                "value": run_summary["average_score"],
            }
        )
        theme_trend.append(
            {
                "run_id": run_id,
                "generated_utc": generated_utc,
                "value": run_summary["theme_count"],
                "themes": run_summary["per_theme_counts"],
            }
        )
        partner_trend.append(
            {
                "run_id": run_id,
                "generated_utc": generated_utc,
                "partners": run_summary["per_partner_counts"],
            }
        )

    deltas = {
        "average_score": {
            "current": 0.0,
            "previous": 0.0,
            "delta": 0.0,
        },
        "theme_count": {
            "current": 0,
            "previous": 0,
            "delta": 0,
        },
        "top_rising_themes": [],
        "top_falling_themes": [],
    }

    if len(runs) >= 2:
        previous = runs[-2]
        current = runs[-1]

        deltas["average_score"] = {
            "current": current["average_score"],
            "previous": previous["average_score"],
            "delta": round(current["average_score"] - previous["average_score"], 4),
        }
        deltas["theme_count"] = {
            "current": current["theme_count"],
            "previous": previous["theme_count"],
            "delta": current["theme_count"] - previous["theme_count"],
        }

        prev_themes = previous["per_theme_counts"]
        curr_themes = current["per_theme_counts"]
        all_themes = sorted(set(prev_themes.keys()) | set(curr_themes.keys()))

        theme_diffs: list[tuple[str, int]] = []
        for theme in all_themes:
            diff = int(curr_themes.get(theme, 0)) - int(prev_themes.get(theme, 0))
            if diff != 0:
                theme_diffs.append((theme, diff))

        rising = sorted([entry for entry in theme_diffs if entry[1] > 0], key=lambda item: (-item[1], item[0]))
        falling = sorted([entry for entry in theme_diffs if entry[1] < 0], key=lambda item: (item[1], item[0]))

        deltas["top_rising_themes"] = [
            {"theme": theme, "delta": delta} for theme, delta in rising[:5]
        ]
        deltas["top_falling_themes"] = [
            {"theme": theme, "delta": delta} for theme, delta in falling[:5]
        ]

    return {
        "runs": runs,
        "score_trend": score_trend,
        "theme_trend": theme_trend,
        "partner_trend": partner_trend,
        "deltas": deltas,
    }


def write_trend_output(trend_data: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(trend_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Wrote trend analysis output to {output_path}")
    return output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute trend analytics across historical weekly analyses")
    parser.add_argument("--analyses-dir", default="analyses", help="Directory containing analysis JSON files")
    parser.add_argument("--output", default="docs/trend_data.json", help="Path to write computed trend JSON")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    trend_data = build_trend_data(analyses_dir=Path(args.analyses_dir))
    write_trend_output(trend_data, output_path=Path(args.output))


if __name__ == "__main__":
    main()
