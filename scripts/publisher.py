#!/usr/bin/env python3
"""Publish markdown summaries to external channels."""

from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests

from log_utils import log


def _markdown_to_slack(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")
    text = re.sub(r"^###\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"^#\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"\*(.+?)\*", r"_\1_", text)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def publish_markdown_to_slack(webhook_url: str, markdown_text: str) -> dict[str, Any]:
    if not webhook_url:
        raise ValueError("Slack webhook URL is required")

    payload = {"text": _markdown_to_slack(markdown_text)}
    try:
        response = requests.post(webhook_url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        body = (exc.response.text or "")[:200] if exc.response is not None else ""
        raise RuntimeError(f"Slack webhook HTTP error (status {status}): {body}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Slack webhook request failed: {exc}") from exc

    return {"channel": "slack", "status": "sent"}


def publish_markdown_to_email(smtp_settings: dict[str, Any], markdown_text: str) -> dict[str, Any]:
    smtp_host = str(smtp_settings.get("host") or "").strip()
    smtp_port = int(smtp_settings.get("port") or 587)
    smtp_username = str(smtp_settings.get("username") or "").strip()
    smtp_password = str(smtp_settings.get("password") or "")
    email_to = str(smtp_settings.get("to") or "").strip()
    run_id = str(smtp_settings.get("run_id") or "")

    if not smtp_host:
        raise ValueError("Email SMTP host is required")
    if not email_to:
        raise ValueError("Email recipient is required")

    msg = EmailMessage()
    msg["Subject"] = f"Weekly Analysis Summary — {run_id}"
    msg["From"] = smtp_username or "no-reply@localhost"
    msg["To"] = email_to
    msg.set_content(markdown_text)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            if smtp_username and smtp_password:
                server.starttls()
                server.ehlo()
                server.login(smtp_username, smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"Email publish failed: {exc}") from exc

    return {"channel": "email", "status": "sent", "to": email_to}


def publish(run_id: str, summary_path: str, config: dict[str, Any]) -> dict[str, Any]:
    summary_file = Path(summary_path)
    if not summary_file.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")

    markdown_text = summary_file.read_text(encoding="utf-8")
    channels_used: list[str] = []
    results: dict[str, Any] = {}

    webhook_url = str(config.get("slack_webhook_url") or "").strip()
    if webhook_url:
        results["slack"] = publish_markdown_to_slack(webhook_url, markdown_text)
        channels_used.append("slack")

    email_enabled = bool(config.get("email_enabled"))
    if email_enabled:
        smtp_settings = {
            "host": config.get("email_smtp_host"),
            "port": config.get("email_smtp_port"),
            "username": config.get("email_username"),
            "password": config.get("email_password"),
            "to": config.get("email_to"),
            "run_id": run_id,
        }
        results["email"] = publish_markdown_to_email(smtp_settings, markdown_text)
        channels_used.append("email")

    if channels_used:
        log(f"Published summary via channels: {', '.join(channels_used)}")
    else:
        log("No publishing channels configured; skipped external publish")

    return {
        "run_id": run_id,
        "summary_path": summary_path,
        "channels_used": channels_used,
        "results": results,
    }
