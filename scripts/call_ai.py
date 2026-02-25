#!/usr/bin/env python3
"""Call an AI provider to produce analysis.json."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call an AI provider for analysis.")
    parser.add_argument("--rows", default="rows.json", help="Rows JSON file.")
    parser.add_argument("--output", default="analysis.json", help="Output JSON file.")
    return parser.parse_args()


def build_prompt(rows: List[Dict[str, Any]], run_id: str) -> str:
    return (
        "You are an analysis system. Return ONLY JSON that matches the schema.\n"
        "Do not include markdown or commentary.\n\n"
        f"Run ID: {run_id}\n"
        "Rows:\n"
        f"{json.dumps(rows, indent=2)}\n"
    )


def call_ai_provider(api_key: str, prompt: str) -> str:
    if api_key == "__MOCK__":
        mock = {
            "generated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat()
            + "Z",
            "run_id": os.environ.get("RUN_ID", "mock"),
            "rows_read": 1,
            "rows_analyzed": 1,
            "sheet_summary": "Mock summary for local testing.",
            "items": [
                {
                    "title": "Mock item",
                    "summary": "Mock summary item for schema validation.",
                    "priority": "medium",
                }
            ],
        }
        return json.dumps(mock, indent=2)

    raise RuntimeError(
        "TODO: Implement provider-specific API call. Set AI_API_KEY or use __MOCK__."
    )


def extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
        raise ValueError("No JSON object found in AI response")
    return text[brace_start : brace_end + 1]


def load_rows(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_run_id() -> str:
    return (
        os.environ.get("RUN_ID")
        or os.environ.get("GITHUB_RUN_ID")
        or dt.datetime.utcnow().strftime("local-%Y%m%d%H%M%S")
    )


def main() -> int:
    args = parse_args()
    api_key = (os.environ.get("AI_API_KEY") or "").strip()
    if not api_key:
        print("Missing AI_API_KEY", file=sys.stderr)
        return 1

    try:
        rows = load_rows(args.rows)
    except Exception as exc:
        print(f"Failed to load rows: {exc}", file=sys.stderr)
        return 1

    run_id = ensure_run_id()
    prompt = build_prompt(rows, run_id)

    try:
        raw_response = call_ai_provider(api_key, prompt)
        json_payload = extract_json(raw_response)
        analysis = json.loads(json_payload)
    except Exception as exc:
        print(f"AI response parsing failed: {exc}", file=sys.stderr)
        return 1

    analysis["run_id"] = run_id
    analysis.setdefault("generated_utc", dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    analysis.setdefault("rows_read", len(rows))
    analysis.setdefault("rows_analyzed", len(rows))

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(analysis, handle, indent=2)

    print(f"Wrote analysis to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
