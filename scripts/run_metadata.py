#!/usr/bin/env python3
"""Generate and persist run metadata for pipeline executions.

Suggested commit message: feat: add run metadata generator and integrate run_id across pipeline
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any


def generate_run_metadata() -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    run_id = now.strftime("run-%Y%m%d-%H%M%S")
    return {
        "run_id": run_id,
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local",
        "commit_sha": os.environ.get("GITHUB_SHA") or None,
        "branch": os.environ.get("GITHUB_REF_NAME") or None,
    }


def save_run_metadata(path: str, metadata: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)
