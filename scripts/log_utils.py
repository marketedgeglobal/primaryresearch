#!/usr/bin/env python3
"""Lightweight logging helpers for pipeline scripts."""

from __future__ import annotations

import datetime as dt
import inspect
import os
import sys


def _timestamp_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caller_script_name() -> str:
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        caller_file = caller.f_globals.get("__file__") if caller else None
        if caller_file:
            return os.path.basename(str(caller_file))
    finally:
        del frame
    return "unknown"


def log(msg: str) -> None:
    print(f"{_timestamp_utc()} [{_caller_script_name()}] {msg}")


def log_error(msg: str) -> None:
    print(f"{_timestamp_utc()} [{_caller_script_name()}] {msg}", file=sys.stderr)
