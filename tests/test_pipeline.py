"""End to end: mock carrier site (in-process) → pipeline → real PostgreSQL. Needs TEST_DATABASE_URL."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import Engine, func, select

from freight_pipeline.config import Settings
from freight_pipeline.extract.http import RetryableHttpError
from freight_pipeline.load.schema import freight_rates, pipeline_runs, rate_history, rejected_rows
from freight_pipeline.models import Rate
from freight_pipeline.pipeline import Pipeline
from freight_pipeline.publish.logistics import PublishResult

pytestmark = pytest.mark.db

EXPECTED_VALID = 290  # 3 carriers x 99 lanes, minus the planted bad rows
EXPECTED_REJECTED = 11


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[list[Rate]] = []

    def publish(self, rates: list[Rate]) -> PublishResult:
        self.calls.append(rates)
        return PublishResult(sent=len(rates), inserted=len(rates))


def _count(engine: Engine, table: object) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())  # type: ignore[arg-type]


def test_first_run_loads_everything_and_records_rejections(
    settings: Settings, engine: Engine, mock_site: httpx.Client
) -> None:
    publisher = FakePublisher()

    summary = Pipeline(settings, engine, http_client=mock_site, publisher=publisher).run()  # type: ignore[arg-type]

    assert summary.status == "succeeded"
    assert summary.extracted_by_source == {"asl": 101, "mcl": 100, "ssc": 101}
    assert summary.load is not None and summary.load.inserted == EXPECTED_VALID
    assert summary.transform is not None and summary.transform.duplicates == 1
    assert _count(engine, freight_rates) == EXPECTED_VALID
    assert _count(engine, rejected_rows) == EXPECTED_REJECTED
    assert _count(engine, rate_history) == EXPECTED_VALID  # first sighting of every price
    assert len(publisher.calls[0]) == EXPECTED_VALID
    assert (settings.report_dir / f"{summary.run_id}.md").read_text(encoding="utf-8").count("|") > 20
    with engine.connect() as conn:
        run = conn.execute(select(pipeline_runs)).one()
    assert (run.status, run.valid, run.rejected, run.published) == (
        "succeeded",
        EXPECTED_VALID,
        EXPECTED_REJECTED,
        EXPECTED_VALID,
    )


def test_second_run_changes_nothing(settings: Settings, engine: Engine, mock_site: httpx.Client) -> None:
    pipeline = Pipeline(settings, engine, http_client=mock_site, publisher=FakePublisher())  # type: ignore[arg-type]
    pipeline.run()

    again = pipeline.run()

    assert again.load is not None
    assert (again.load.inserted, again.load.updated, again.load.unchanged) == (0, 0, EXPECTED_VALID)
    assert _count(engine, freight_rates) == EXPECTED_VALID
    assert _count(engine, rate_history) == EXPECTED_VALID


def test_price_changes_are_updated_and_kept_in_history(
    settings: Settings, engine: Engine, mock_site: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(settings, engine, http_client=mock_site, publisher=FakePublisher())  # type: ignore[arg-type]
    pipeline.run()

    monkeypatch.setenv("MOCK_MARKET_DAY", "3")  # the market moves
    moved = pipeline.run()

    assert moved.load is not None and moved.load.updated > 0
    assert moved.load.inserted == 0
    assert _count(engine, freight_rates) == EXPECTED_VALID
    assert _count(engine, rate_history) == EXPECTED_VALID + moved.load.updated
    assert moved.moves and abs(moved.moves[0].change_pct) >= abs(moved.moves[-1].change_pct)


def test_retries_carry_the_run_through_a_flaky_site(
    settings: Settings, engine: Engine, mock_site: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_FLAKY_EVERY", "3")
    monkeypatch.setattr("freight_pipeline.extract.http.time.sleep", lambda _: None)

    summary = Pipeline(settings, engine, http_client=mock_site, publisher=FakePublisher()).run(publish=False)  # type: ignore[arg-type]

    assert summary.status == "succeeded"
    assert summary.fetch is not None and summary.fetch.retries > 0
    assert summary.load is not None and summary.load.inserted == EXPECTED_VALID


def test_replay_reprocesses_raw_files_without_crawling(
    settings: Settings, engine: Engine, mock_site: httpx.Client
) -> None:
    pipeline = Pipeline(settings, engine, http_client=mock_site, publisher=FakePublisher())  # type: ignore[arg-type]
    original = pipeline.run(publish=False)
    offline = Pipeline(settings, engine, http_client=httpx.Client(base_url="http://unreachable.invalid"))

    replayed = offline.replay(original.run_id)

    assert replayed.extracted_by_source == original.extracted_by_source
    assert replayed.load is not None and replayed.load.unchanged == EXPECTED_VALID


def test_a_run_that_runs_out_of_retries_is_recorded_as_failed(
    settings: Settings, engine: Engine, mock_site: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_FLAKY_EVERY", "1")  # the carrier is down: every request answers 503
    monkeypatch.setattr("freight_pipeline.extract.http.time.sleep", lambda _: None)

    with pytest.raises(RetryableHttpError):
        Pipeline(settings, engine, http_client=mock_site).run(sources=["ssc"])

    with engine.connect() as conn:
        run = conn.execute(select(pipeline_runs)).one()
    assert run.status == "failed"
    assert "503" in run.error
    assert run.http_requests == settings.max_attempts
