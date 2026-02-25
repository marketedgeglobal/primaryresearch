#!/usr/bin/env python3
"""Validate analysis JSON against a JSON Schema file.

Usage:
    python scripts/validate_schema.py --schema schemas/analysis_schema.json --input analysis.json

Suggested commit message: feat: add scripts/validate_schema.py for JSON Schema validation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import ValidationError, validate
from log_utils import log, log_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate analysis JSON with JSON Schema.")
    parser.add_argument("--schema", required=True, help="Path to JSON Schema file")
    parser.add_argument("--input", required=True, help="Path to analysis JSON file")
    return parser.parse_args()


def write_error_file(message: str) -> None:
    error_path = Path("schema_validation_error.json")
    payload = {"error": message}
    with error_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def main() -> int:
    log("Script start")
    args = parse_args()

    try:
        log("Loading schema and analysis files")
        with open(args.schema, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        with open(args.input, "r", encoding="utf-8") as fh:
            analysis = json.load(fh)
    except Exception as exc:
        message = f"Failed to load input files: {exc}"
        log_error(message)
        try:
            write_error_file(message)
        except Exception:
            pass
        return 1

    try:
        log("Validating analysis against schema")
        validate(instance=analysis, schema=schema)
        log("Schema validation passed")
        return 0
    except ValidationError as exc:
        message = f"Schema validation failed: {exc.message}"
    except Exception as exc:
        message = f"Schema validation failed: {exc}"

    log_error(message)
    try:
        write_error_file(message)
    except Exception as write_exc:
        log_error(f"Also failed to write schema_validation_error.json: {write_exc}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
