#!/usr/bin/env python3
"""Unified error handling for pipeline scripts.

Suggested commit message:
feat: add unified error handling and recovery layer across pipeline
"""

from __future__ import annotations

import datetime as dt
import json
from functools import wraps
from typing import Any, Callable, TypeVar

from log_utils import log_error


class PipelineError(Exception):
    """Expected pipeline failure with a safe user-facing message."""


def _timestamp_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handle_exception(e: Exception, context: str) -> None:
    error_type = type(e).__name__
    message = str(e)

    log_error(f"{context}: {message}")

    payload = {
        "error_type": error_type,
        "message": message,
        "context": context,
        "timestamp_utc": _timestamp_utc(),
    }
    with open("pipeline_error.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    raise SystemExit(1)


F = TypeVar("F", bound=Callable[..., Any])


def safe_run(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except PipelineError as exc:
            handle_exception(exc, context=fn.__name__)
        except Exception as exc:
            handle_exception(PipelineError("Unexpected pipeline failure"), context=fn.__name__)

    return wrapper  # type: ignore[return-value]
