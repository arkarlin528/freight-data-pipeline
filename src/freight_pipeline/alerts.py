from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def send_alert(webhook_url: str, text: str) -> None:
    """Post to a Slack incoming webhook. Never raises: a broken alert must not hide the original failure."""
    try:
        httpx.post(webhook_url, json={"text": text}, timeout=10).raise_for_status()
    except httpx.HTTPError:
        log.exception("could not send alert")
