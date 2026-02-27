#!/usr/bin/env python3
"""Centralized configuration loader for the weekly analysis pipeline.

Suggested commit message:
feat: add centralized pipeline config loader and integrate across scripts
"""

from __future__ import annotations

import os
from typing import Any


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value).strip())


def _as_float(value: str | float | int | None, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    return float(str(value).strip())


def load_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "spreadsheet_id": os.environ.get("SPREADSHEET_ID") or "",
        "range": os.environ.get("SHEET_RANGE") or "Sheet1!A1:J50",
        "service_account_path": os.environ.get("SERVICE_ACCOUNT_PATH") or "/tmp/gservice.json",
        "provider": os.environ.get("AI_PROVIDER") or "openai",
        "api_key": os.environ.get("AI_API_KEY") or "",
        "model": os.environ.get("AI_MODEL") or "gpt-4o-mini",
        "output_dir": os.environ.get("OUTPUT_DIR") or "analyses",
        "allow_mock": _as_bool(os.environ.get("ALLOW_MOCK"), True),
        "timeout_seconds": _as_int(os.environ.get("AI_TIMEOUT_SECONDS"), 60),
        "slack_webhook_url": os.environ.get("SLACK_WEBHOOK_URL") or "",
        "email_enabled": _as_bool(os.environ.get("EMAIL_ENABLED"), False),
        "email_smtp_host": os.environ.get("EMAIL_SMTP_HOST") or "",
        "email_smtp_port": _as_int(os.environ.get("EMAIL_SMTP_PORT"), 587),
        "email_username": os.environ.get("EMAIL_USERNAME") or "",
        "email_password": os.environ.get("EMAIL_PASSWORD") or "",
        "email_to": os.environ.get("EMAIL_TO") or "",
    }

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                cfg[key] = value

    provider = str(cfg.get("provider", "openai")).strip().lower()
    cfg["provider"] = provider

    if not cfg.get("spreadsheet_id"):
        raise ValueError("Missing required configuration: SPREADSHEET_ID")

    api_key = str(cfg.get("api_key") or "").strip()
    allow_mock = _as_bool(cfg.get("allow_mock"), True)
    if provider != "mock" and not api_key:
        raise ValueError("Missing required configuration: AI_API_KEY")
    if provider == "mock" and not allow_mock:
        raise ValueError("Mock provider is disabled by configuration")

    cfg["allow_mock"] = allow_mock
    cfg["timeout_seconds"] = _as_int(cfg.get("timeout_seconds"), 60)
    cfg["api_key"] = api_key
    return cfg


def load_insights_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "insight_min_count": _as_int(os.environ.get("INSIGHT_MIN_COUNT"), 3),
        "insight_delta_threshold": _as_float(os.environ.get("INSIGHT_DELTA_THRESHOLD"), 2.0),
        "insight_concentration_threshold": _as_float(os.environ.get("INSIGHT_CONCENTRATION_THRESHOLD"), 0.6),
        "insight_anomaly_multiplier": _as_float(os.environ.get("INSIGHT_ANOMALY_MULTIPLIER"), 2.0),
        "insight_template_path": os.environ.get("INSIGHT_TEMPLATE_PATH") or "scripts/templates/insight_templates.yml",
    }

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                cfg[key] = value

    cfg["insight_min_count"] = _as_int(cfg.get("insight_min_count"), 3)
    cfg["insight_delta_threshold"] = _as_float(cfg.get("insight_delta_threshold"), 2.0)
    cfg["insight_concentration_threshold"] = _as_float(cfg.get("insight_concentration_threshold"), 0.6)
    cfg["insight_anomaly_multiplier"] = _as_float(cfg.get("insight_anomaly_multiplier"), 2.0)
    return cfg
