#!/usr/bin/env python3
"""Read a Google Sheet range and write rows as JSON objects.

Usage:
    python scripts/fetch_sheet.py --service-account /path/key.json \
    --spreadsheet-id <ID> --range 'Sheet1!A1:Z' --output-dir analyses [--limit 100]
"""

from __future__ import annotations

import argparse
from typing import Any

from config import load_config
from errors import PipelineError, handle_exception, safe_run
from google.oauth2 import service_account
from googleapiclient.discovery import build
from log_utils import log
from output_writer import write_rows_output
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
    parser.add_argument("--run-id", default=None, help="Run identifier override")
    parser.add_argument("--output-dir", default=None, help="Output directory for generated files")
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
    metadata_run_id = metadata["run_id"]
    args = parse_args()
    run_id = args.run_id or metadata_run_id
    log(f"Run ID: {run_id}")

    try:
        cfg = load_config(
            {
                "spreadsheet_id": args.spreadsheet_id,
                "service_account_path": args.service_account,
                "range": args.range_name,
                "output_dir": args.output_dir,
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
        output_path = write_rows_output(run_id, rows, cfg["output_dir"])
    except Exception as exc:
        raise PipelineError("Failed to write rows output")

    log(f"[{run_id}] Success: wrote {len(rows)} rows to {output_path}")
    _ = handle_exception


if __name__ == "__main__":
    main()
