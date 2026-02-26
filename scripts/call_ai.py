#!/usr/bin/env python3
"""Build an AI analysis prompt from rows.json and write analysis.json.

Usage:
    python scripts/call_ai.py --input analyses/rows-run-1234.json --run-id run-1234 --api-key __MOCK__ --output-dir analyses

Suggested commit message: feat: add OpenAI provider integration to call_ai.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from typing import Any

import requests
from config import load_config
from errors import PipelineError, handle_exception, safe_run
from log_utils import log, log_error
from output_writer import write_analysis_output, write_error_output
from run_metadata import generate_run_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call an AI provider and write analysis JSON.")
    parser.add_argument("--input", required=True, help="Path to rows.json")
    parser.add_argument("--run-id", default=None, help="Run identifier")
    parser.add_argument("--api-key", default=None, help='Provider API key or "__MOCK__"')
    parser.add_argument("--provider", default=None, help="AI provider (openai or mock)")
    parser.add_argument("--model", default=None, help="AI model name")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="AI request timeout in seconds")
    parser.add_argument("--output-dir", default=None, help="Output directory for generated files")
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


def call_openai(api_key: str, prompt: str, model: str, timeout_seconds: int) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        body = exc.response.text[:500] if exc.response is not None else str(exc)
        raise RuntimeError(f"OpenAI API HTTP error (status {status}): {body}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("OpenAI API response format was unexpected") from exc

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI API returned empty response content")

    return content


def call_ai_provider(provider: str, api_key: str, prompt: str, model: str, timeout_seconds: int) -> str:
    if provider == "mock" or api_key == "__MOCK__":
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
    return call_openai(api_key, prompt, model, timeout_seconds)


def extract_json_from_fence(raw: str) -> str | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r"```\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    return match.group(1) if match else None


@safe_run
def main() -> None:
    log("Script start")
    metadata = generate_run_metadata()
    metadata_run_id = metadata["run_id"]
    log(f"Run ID: {metadata_run_id}")
    args = parse_args()

    try:
        cfg = load_config(
            {
                "provider": args.provider,
                "api_key": args.api_key,
                "model": args.model,
                "timeout_seconds": args.timeout_seconds,
                "output_dir": args.output_dir,
            }
        )
    except Exception as exc:
        raise PipelineError(f"Configuration error: {exc}")

    log("Config keys in use: provider, model, timeout_seconds, allow_mock")
    effective_run_id = args.run_id or metadata_run_id

    try:
        log("Loading input rows")
        with open(args.input, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            raise ValueError("input JSON must be an array of row objects")
    except Exception as exc:
        raise PipelineError("Failed to read input rows")

    log("Building prompt")
    prompt = build_prompt(rows, effective_run_id)

    try:
        log("Calling AI provider")
        raw = call_ai_provider(
            cfg["provider"],
            cfg["api_key"],
            prompt,
            cfg["model"],
            cfg["timeout_seconds"],
        )
    except Exception as exc:
        raise PipelineError("AI provider call failed")

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
            log_error("AI response parsing failed; writing error payload")
            error_path = write_error_output(effective_run_id, error_payload, cfg["output_dir"])
            log(f"[{effective_run_id}] Wrote error output: {error_path}")
        except Exception as exc:
            raise PipelineError("Failed to write AI parse-error output")
        raise PipelineError("Failed to parse AI output as JSON")

    parsed["run_id"] = effective_run_id

    try:
        log("Writing analysis output")
        output_path = write_analysis_output(effective_run_id, parsed, cfg["output_dir"])
    except Exception as exc:
        raise PipelineError("Failed to write analysis output")

    log(f"[{effective_run_id}] Success: wrote analysis to {output_path}")
    _ = handle_exception


if __name__ == "__main__":
    main()
