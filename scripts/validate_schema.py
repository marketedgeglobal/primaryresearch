#!/usr/bin/env python3
"""Validate analysis.json against the JSON schema."""

from __future__ import annotations

import argparse
import json
import sys

from jsonschema import ValidationError, validate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate analysis JSON.")
    parser.add_argument("--analysis", default="analysis.json", help="Analysis JSON file.")
    parser.add_argument(
        "--schema", default="schemas/analysis_schema.json", help="Schema JSON file."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with open(args.analysis, "r", encoding="utf-8") as handle:
            analysis = json.load(handle)
        with open(args.schema, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
    except Exception as exc:
        print(f"Failed to load files: {exc}", file=sys.stderr)
        return 1

    try:
        validate(instance=analysis, schema=schema)
    except ValidationError as exc:
        print(f"Schema validation failed: {exc.message}", file=sys.stderr)
        return 1

    print("Schema validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
