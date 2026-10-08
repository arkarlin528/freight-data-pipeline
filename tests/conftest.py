from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from freight_pipeline.config import Settings
from mock_site.app import app as mock_app

MOCK_BASE = "http://testserver"


@pytest.fixture
def mock_site() -> Iterator[httpx.Client]:
    """The mock carrier site, in-process (no network). TestClient is an httpx.Client."""
    with TestClient(mock_app, base_url=MOCK_BASE) as client:
        yield client


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=os.getenv(
            "TEST_DATABASE_URL", "postgresql+psycopg://auction_dev:auction_dev_local@localhost/freight_pipeline_test"
        ),
        source_base_url=MOCK_BASE,
        min_request_interval=0,
        honour_crawl_delay=False,
        max_attempts=4,
        raw_dir=tmp_path / "raw",
        report_dir=tmp_path / "reports",
        logistics_api_url=None,
        logistics_api_key=None,
        slack_webhook_url=None,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="session")
def _migrated_engine() -> Engine:
    url = os.getenv(
        "TEST_DATABASE_URL", "postgresql+psycopg://auction_dev:auction_dev_local@localhost/freight_pipeline_test"
    )
    engine = create_engine(url)
    try:
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not available for tests: {exc}")

    # Run the real Alembic migrations, so the tests also prove the migrations work.
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS rejected_rows, rate_history, freight_rates, pipeline_runs, alembic_version "
                "CASCADE"
            )
        )
    command.upgrade(config, "head")
    return engine


@pytest.fixture
def engine(_migrated_engine: Engine) -> Engine:
    with _migrated_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE rejected_rows, rate_history, freight_rates, pipeline_runs RESTART IDENTITY CASCADE")
        )
    return _migrated_engine
