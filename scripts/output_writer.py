#!/usr/bin/env python3
"""Centralized structured JSON output writer helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from log_utils import log


def write_json(path: str, data: Any) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    final_path = str(target)
    log(f"Wrote JSON output to {final_path}")
    return final_path


def write_analysis_output(run_id: str, analysis_dict: dict[str, Any], output_dir: str) -> str:
    path = f"{output_dir}/analysis-{run_id}.json"
    return write_json(path, analysis_dict)


def write_rows_output(run_id: str, rows_dict: Any, output_dir: str) -> str:
    path = f"{output_dir}/rows-{run_id}.json"
    return write_json(path, rows_dict)


def write_error_output(run_id: str, error_dict: dict[str, Any], output_dir: str) -> str:
    path = f"{output_dir}/error-{run_id}.json"
    return write_json(path, error_dict)
