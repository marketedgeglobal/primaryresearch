#!/usr/bin/env python3
"""Fetch rows from a Google Sheet and write rows.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from google.oauth2 import service_account
from googleapiclient.discovery import build


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch rows from a Google Sheet.")
    parser.add_argument(
        "--service-account",
        default="/tmp/gservice.json",
        help="Path to service account JSON file.",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Spreadsheet ID (defaults to SPREADSHEET_ID env var).",
    )
    parser.add_argument(
        "--range",
        dest="range_name",
        default="Sheet1!A1:Z",
        help="Sheet range to read.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to return.",
    )
    parser.add_argument(
        "--output",
        default="rows.json",
        help="Output JSON file.",
    )
    return parser.parse_args()


def normalize_rows(values: List[List[str]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    rows: List[Dict[str, Any]] = []
    for raw_row in values[1:]:
        item: Dict[str, Any] = {}
        for idx, key in enumerate(header):
            if not key:
                continue
            item[key] = raw_row[idx] if idx < len(raw_row) else ""
        rows.append(item)
    return rows


def main() -> int:
    args = parse_args()
    spreadsheet_id = args.spreadsheet_id or ""
    if not spreadsheet_id:
        spreadsheet_id = (os.environ.get("SPREADSHEET_ID") or "").strip()
    if not spreadsheet_id:
        print("Missing SPREADSHEET_ID (arg or env)", file=sys.stderr)
        return 1

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    try:
        creds = service_account.Credentials.from_service_account_file(
            args.service_account, scopes=scopes
        )
    except Exception as exc:
        print(f"Failed to load service account: {exc}", file=sys.stderr)
        return 1

    try:
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=args.range_name)
            .execute()
        )
    except Exception as exc:
        print(f"Failed to fetch sheet values: {exc}", file=sys.stderr)
        return 1

    values = result.get("values", [])
    rows = normalize_rows(values)
    if args.limit is not None:
        rows = rows[: args.limit]

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)

    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
