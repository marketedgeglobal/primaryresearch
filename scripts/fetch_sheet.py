#!/usr/bin/env python3
"""Read a Google Sheet range and write rows as JSON objects.

Usage:
    python scripts/fetch_sheet.py --service-account /path/key.json \
        --spreadsheet-id <ID> --range 'Sheet1!A1:Z' --out rows.json [--limit 100]
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from config import load_config
from errors import PipelineError, handle_exception, safe_run
from google.oauth2 import service_account
from googleapiclient.discovery import build
from log_utils import log, log_error
from run_metadata import generate_run_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch rows from a Google Sheet.")
    parser.add_argument(
        "--service-account",
        default=None,
        help="Path to service account JSON file.",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Spreadsheet ID.",
    )
    parser.add_argument(
        "--range",
        dest="range_name",
        default=None,
        help="Sheet range to read.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of data rows to include; 0 means no limit.",
    )
    return parser.parse_args()


def normalize_rows(values: list[list[str]]) -> list[dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    rows: list[dict[str, Any]] = []
    for raw_row in values[1:]:
        item: dict[str, Any] = {}
        for idx, key in enumerate(header):
            if not key:
                continue
            item[key] = raw_row[idx] if idx < len(raw_row) else ""
        rows.append(item)
    return rows


@safe_run
def main() -> None:
    log("Script start")
    metadata = generate_run_metadata()
    run_id = metadata["run_id"]
    log(f"Run ID: {run_id}")
    args = parse_args()

    try:
        cfg = load_config(
            {
                "spreadsheet_id": args.spreadsheet_id,
                "service_account_path": args.service_account,
                "range": args.range_name,
            }
        )
    except Exception as exc:
        raise PipelineError(f"Configuration error: {exc}")

    log("Config keys in use: spreadsheet_id, range, service_account_path, timeout_seconds")

    if args.limit < 0:
        raise PipelineError("Invalid limit value")

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    try:
        log(f"[{run_id}] Loading service account credentials")
        creds = service_account.Credentials.from_service_account_file(
            cfg["service_account_path"], scopes=scopes
        )
    except Exception as exc:
        raise PipelineError("Failed to load service account credentials")

    try:
        log(f"[{run_id}] Fetching sheet values")
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=cfg["spreadsheet_id"], range=cfg["range"])
            .execute()
        )
    except Exception as exc:
        raise PipelineError("Failed to fetch sheet values")

    values = result.get("values", [])
    rows = normalize_rows(values)
    if args.limit > 0:
        rows = rows[: args.limit]

    try:
        log(f"[{run_id}] Writing rows output")
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, ensure_ascii=False)
    except Exception as exc:
        raise PipelineError("Failed to write rows output")

    log(f"[{run_id}] Success: wrote {len(rows)} rows to {args.out}")
    _ = handle_exception


if __name__ == "__main__":
    main()
