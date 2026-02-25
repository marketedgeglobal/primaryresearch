#!/usr/bin/env python3
"""Read a Google Sheet range and write rows as JSON objects.

Usage:
    python scripts/fetch_sheet.py --service-account /path/key.json \
        --spreadsheet-id <ID> --range 'Sheet1!A1:Z' --out rows.json [--limit 100]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from log_utils import log, log_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch rows from a Google Sheet.")
    parser.add_argument(
        "--service-account",
        required=True,
        help="Path to service account JSON file.",
    )
    parser.add_argument(
        "--spreadsheet-id",
        required=True,
        help="Spreadsheet ID.",
    )
    parser.add_argument(
        "--range",
        dest="range_name",
        required=True,
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


def main() -> int:
    log("Script start")
    args = parse_args()
    if args.limit < 0:
        log_error("--limit must be >= 0")
        return 1

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    try:
        log("Loading service account credentials")
        creds = service_account.Credentials.from_service_account_file(
            args.service_account, scopes=scopes
        )
    except Exception as exc:
        log_error(f"Failed to load service account: {exc}")
        return 1

    try:
        log("Fetching sheet values")
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=args.spreadsheet_id, range=args.range_name)
            .execute()
        )
    except Exception as exc:
        log_error(f"Failed to fetch sheet values: {exc}")
        return 1

    values = result.get("values", [])
    rows = normalize_rows(values)
    if args.limit > 0:
        rows = rows[: args.limit]

    try:
        log("Writing rows output")
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, ensure_ascii=False)
    except Exception as exc:
        log_error(f"Failed to write output JSON: {exc}")
        return 1

    log(f"Success: wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
