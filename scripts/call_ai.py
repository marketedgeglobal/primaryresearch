#!/usr/bin/env python3
"""Build an AI analysis prompt from rows.json and write analysis.json.

Usage:
    python scripts/call_ai.py --input rows.json --run-id 12345 --api-key __MOCK__ --out analysis.json

Suggested commit message: feat: add scripts/call_ai.py with prompt builder and mock provider
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call an AI provider and write analysis JSON.")
    parser.add_argument("--input", required=True, help="Path to rows.json")
    parser.add_argument("--run-id", required=True, help="Run identifier")
    parser.add_argument("--api-key", required=True, help='Provider API key or "__MOCK__"')
    parser.add_argument("--out", required=True, help="Output JSON path")
    return parser.parse_args()


def build_prompt(rows: list[dict[str, Any]], run_id: str) -> str:
    rows_preview = rows[:200]
    schema_description = {
        "generated_utc": "string, UTC timestamp",
        "run_id": "string, copied from input run_id",
        "rows_read": "integer, total rows in input",
        "rows_analyzed": "integer, rows actually analyzed",
        "sheet_summary": "string, concise overall summary",
        "top_tags": "array of strings, most common themes",
        "counts_by_status": "object, status -> count",
        "deadline_overview": "object, summary of upcoming/overdue deadlines",
        "items": "array of objects with at least title and summary; optional row_id,tags,scores,priority,recommendation,notes",
    }

    return (
        "You are a strict data analysis assistant. Return ONLY valid JSON.\n"
        "No markdown, no code fences, no prose.\n"
        f"run_id: {run_id}\n"
        f"rows_total: {len(rows)}\n"
        f"rows_included_in_prompt: {len(rows_preview)}\n\n"
        "Required top-level keys:\n"
        "generated_utc, run_id, rows_read, rows_analyzed, sheet_summary, "
        "top_tags, counts_by_status, deadline_overview, items\n\n"
        "Schema guide:\n"
        f"{json.dumps(schema_description, ensure_ascii=False)}\n\n"
        "Rows JSON:\n"
        f"{json.dumps(rows_preview, ensure_ascii=False)}\n"
    )


def call_ai_provider(api_key: str, prompt: str) -> str:
    _ = prompt
    if api_key == "__MOCK__":
        mock_payload = {
            "generated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "run_id": "mock-run",
            "rows_read": 2,
            "rows_analyzed": 2,
            "sheet_summary": "Local mock summary.",
            "top_tags": ["risk", "follow-up"],
            "counts_by_status": {"open": 1, "closed": 1},
            "deadline_overview": {
                "overdue_count": 0,
                "due_7_days_count": 1,
                "notes": "Mock deadline overview",
            },
            "items": [
                {
                    "title": "Mock item",
                    "summary": "Mock summary for local validation.",
                    "priority": "medium",
                }
            ],
        }
        return json.dumps(mock_payload, ensure_ascii=False)

    raise RuntimeError(
        "TODO: Implement real provider call in call_ai_provider(api_key, prompt), including endpoint, "
        "headers, model, timeout, and retry handling for your AI service."
    )


def extract_json_from_fence(raw: str) -> str | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r"```\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    return match.group(1) if match else None


def write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def main() -> int:
    args = parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            raise ValueError("input JSON must be an array of row objects")
    except Exception as exc:
        print(f"Failed to read input rows: {exc}", file=sys.stderr)
        return 1

    prompt = build_prompt(rows, args.run_id)

    try:
        raw = call_ai_provider(args.api_key, prompt)
    except Exception as exc:
        print(f"AI provider call failed: {exc}", file=sys.stderr)
        return 1

    parsed: dict[str, Any] | None = None
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            parsed = loaded
        else:
            raise ValueError("AI output is not a JSON object")
    except Exception:
        fenced = extract_json_from_fence(raw)
        if fenced:
            try:
                loaded = json.loads(fenced)
                if isinstance(loaded, dict):
                    parsed = loaded
            except Exception:
                parsed = None

    if parsed is None:
        error_payload = {
            "error": "Could not parse AI response as JSON object",
            "raw": raw,
        }
        try:
            write_json(args.out, error_payload)
        except Exception as exc:
            print(f"Failed to write output file: {exc}", file=sys.stderr)
            return 1
        print("Failed to parse AI output as JSON", file=sys.stderr)
        return 1

    parsed["run_id"] = args.run_id

    try:
        write_json(args.out, parsed)
    except Exception as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote analysis to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
