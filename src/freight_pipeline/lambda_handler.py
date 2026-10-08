"""
AWS Lambda entry point (container image), triggered by an EventBridge schedule such as cron(0 22 * * ? *),
which is 05:00 in Bangkok. Settings come from environment variables; secrets from SSM/Secrets Manager
injected as env vars. The raw zone should point at /tmp (or S3) because the Lambda filesystem is read-only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine

from freight_pipeline import logging_setup
from freight_pipeline.config import get_settings
from freight_pipeline.pipeline import Pipeline


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    logging_setup.configure(json_output=True)
    settings = get_settings()
    summary = Pipeline(settings, create_engine(settings.database_url, pool_pre_ping=True)).run(
        sources=event.get("sources"), publish=event.get("publish", True)
    )
    t, ld = summary.transform, summary.load
    return {
        "run_id": summary.run_id,
        "status": summary.status,
        "valid": len(t.rates) if t else 0,
        "rejected": len(t.rejections) if t else 0,
        "changed": ld.updated if ld else 0,
    }
