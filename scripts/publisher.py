#!/usr/bin/env python3
"""Publish markdown summaries to external channels."""

from __future__ import annotations

import json
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests

from log_utils import log


def _load_high_severity_alerts(run_id: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    output_dir = str(config.get("output_dir") or "analyses")
    alerts_path = Path(output_dir) / f"alerts-{run_id}.json"
    docs_link = f"docs/alerts-{run_id}.md"

    if not alerts_path.exists():
        return [], docs_link

    try:
        payload = json.loads(alerts_path.read_text(encoding="utf-8"))
    except Exception:
        return [], docs_link

    alerts = payload.get("alerts") if isinstance(payload, dict) else []
    if not isinstance(alerts, list):
        return [], docs_link

    high_alerts = [item for item in alerts if isinstance(item, dict) and str(item.get("severity")) == "high"]
    return high_alerts, docs_link


def _append_alerts_markdown(markdown_text: str, run_id: str, high_alerts: list[dict[str, Any]], alerts_link: str) -> str:
    if not high_alerts:
        return markdown_text

    lines = [markdown_text.rstrip(), "", "## High Severity Alerts", ""]
    for alert in high_alerts[:5]:
        title = str(alert.get("title") or "Untitled alert")
        summary = str(alert.get("summary") or "")
        confidence = float(alert.get("confidence") or 0.0)
        lines.append(f"- **{title}** (confidence: {confidence:.2f})")
        if summary:
            lines.append(f"  - {summary}")

    lines.extend(["", f"Full alert report: {alerts_link}"])
    return "\n".join(lines).rstrip() + "\n"


def _load_followup_highlights(run_id: str, config: dict[str, Any]) -> list[dict[str, str]]:
    output_dir = str(config.get("output_dir") or "analyses")
    alerts_path = Path(output_dir) / f"alerts-{run_id}.json"
    if not alerts_path.exists():
        return []

    try:
        payload = json.loads(alerts_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    alerts = payload.get("alerts") if isinstance(payload, dict) else []
    if not isinstance(alerts, list):
        return []

    high_followups = [
        item
        for item in alerts
        if isinstance(item, dict)
        and str(item.get("severity")) == "high"
        and str(item.get("followup_path") or "").strip()
    ]
    if not high_followups:
        return []

    high_followups.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)

    highlights: list[dict[str, str]] = []
    for alert in high_followups[:2]:
        title = str(alert.get("title") or "Untitled alert")
        followup_path = str(alert.get("followup_path") or "").strip()
        followup_doc_name = Path(followup_path).name
        followup_link = f"docs/{followup_doc_name}"

        teaser = "Follow-up generated."
        followup_json = Path(output_dir) / f"{Path(followup_doc_name).stem}.json"
        if followup_json.exists():
            try:
                followup_payload = json.loads(followup_json.read_text(encoding="utf-8"))
                deeper = str(followup_payload.get("deeper_analysis") or "").strip()
                if deeper:
                    teaser = deeper[:180] + ("..." if len(deeper) > 180 else "")
            except Exception:
                teaser = "Follow-up generated."

        highlights.append({"title": title, "teaser": teaser, "link": followup_link})

    return highlights


def _append_followups_markdown(markdown_text: str, followup_highlights: list[dict[str, str]]) -> str:
    if not followup_highlights:
        return markdown_text

    lines = [markdown_text.rstrip(), "", "## Follow-Up Investigations", ""]
    for item in followup_highlights:
        title = str(item.get("title") or "Untitled follow-up")
        teaser = str(item.get("teaser") or "Follow-up generated.")
        link = str(item.get("link") or "")

        lines.append(f"- **{title}**")
        lines.append(f"  - {teaser}")
        if link:
            lines.append(f"  - Full follow-up: {link}")

    return "\n".join(lines).rstrip() + "\n"


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
    high_alerts, alerts_link = _load_high_severity_alerts(run_id, config)
    followup_highlights = _load_followup_highlights(run_id, config)
    publish_markdown = _append_alerts_markdown(markdown_text, run_id, high_alerts, alerts_link)
    publish_markdown = _append_followups_markdown(publish_markdown, followup_highlights)
    channels_used: list[str] = []
    results: dict[str, Any] = {}

    webhook_url = str(config.get("slack_webhook_url") or "").strip()
    if webhook_url:
        results["slack"] = publish_markdown_to_slack(webhook_url, publish_markdown)
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
        results["email"] = publish_markdown_to_email(smtp_settings, publish_markdown)
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
