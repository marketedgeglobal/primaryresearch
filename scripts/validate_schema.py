#!/usr/bin/env python3
"""Validate analysis JSON against a JSON Schema file.

Usage:
    python scripts/validate_schema.py --schema schemas/analysis_schema.json --input analysis.json

Suggested commit message: feat: add scripts/validate_schema.py for JSON Schema validation
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import load_config
from errors import PipelineError, handle_exception, safe_run
from jsonschema import ValidationError, validate
from log_utils import log, log_error
from run_metadata import generate_run_metadata


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


@safe_run
def main() -> None:
    log("Script start")
    metadata = generate_run_metadata()
    run_id = metadata["run_id"]
    log(f"Run ID: {run_id}")

    try:
        cfg = load_config()
    except Exception as exc:
        raise PipelineError(f"Configuration error: {exc}")

    log("Config keys in use: output_dir, provider, timeout_seconds")

    args = parse_args()

    try:
        log(f"[{run_id}] Loading schema and analysis files")
        with open(args.schema, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        with open(args.input, "r", encoding="utf-8") as fh:
            analysis = json.load(fh)
    except Exception as exc:
        raise PipelineError("Failed to load schema or analysis files")

    try:
        log(f"[{run_id}] Validating analysis against schema")
        validate(instance=analysis, schema=schema)
        log(f"[{run_id}] Schema validation passed")
    except ValidationError as exc:
        raise PipelineError(f"Schema validation failed: {exc.message}")
    except Exception as exc:
        raise PipelineError("Schema validation failed")

    _ = handle_exception


if __name__ == "__main__":
    main()
