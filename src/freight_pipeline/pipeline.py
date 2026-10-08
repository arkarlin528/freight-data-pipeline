"""
Orchestrates one run: extract (to the raw zone) → parse → transform/validate → load → publish → report.
Every run is recorded in pipeline_runs, so failures are visible and re-runs are traceable.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import httpx
from sqlalchemy import Engine

from freight_pipeline.alerts import send_alert
from freight_pipeline.config import Settings
from freight_pipeline.extract.http import PoliteClient
from freight_pipeline.extract.raw_store import RawStore
from freight_pipeline.extract.sources import Source, build_sources
from freight_pipeline.load.repository import Repository
from freight_pipeline.models import RawRecord
from freight_pipeline.publish.logistics import LogisticsPublisher
from freight_pipeline.report import RunSummary, render
from freight_pipeline.transform.normalize import transform

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        http_client: httpx.Client | None = None,
        publisher: LogisticsPublisher | None = None,
    ):
        self.settings = settings
        self.repo = Repository(engine)
        self._http_client = http_client
        self._publisher = publisher

    def run(self, sources: list[str] | None = None, publish: bool = True, run_id: str | None = None) -> RunSummary:
        """Crawl the carriers now, then process what was downloaded."""
        names = sources or self.settings.sources
        run_id = run_id or str(uuid.uuid4())
        store = RawStore(self.settings.raw_dir, run_id)
        client = PoliteClient(
            self.settings.user_agent,
            self.settings.min_request_interval,
            self.settings.request_timeout,
            self.settings.max_attempts,
            client=self._http_client,
            honour_crawl_delay=self.settings.honour_crawl_delay,
        )
        summary = RunSummary(run_id=run_id, status="running", fetch=client.stats)
        self.repo.start_run(run_id, names)
        log.info("run started", extra={"run_id": run_id, "sources": names})

        try:
            for source in self._sources(names):
                source.fetch(client, store)
                log.info("fetched", extra={"run_id": run_id, "source": source.name})
            self._process(summary, store, names, publish)
        except Exception as exc:  # recorded, reported and alerted, then re-raised for a non-zero exit
            self._fail(summary, exc)
            raise
        finally:
            if self._http_client is None:
                client.close()
        return summary

    def replay(self, run_id: str, publish: bool = False) -> RunSummary:
        """Re-parse a previous run's raw files (e.g. after fixing a parser) without crawling again."""
        store = RawStore(self.settings.raw_dir, run_id)
        if not store.run_dir.exists():
            raise FileNotFoundError(f"no raw data for run {run_id} under {self.settings.raw_dir}")
        names = sorted(p.name for p in store.run_dir.iterdir() if p.is_dir())
        new_id = str(uuid.uuid4())
        summary = RunSummary(run_id=new_id, status="running")
        self.repo.start_run(new_id, [f"replay:{run_id}"])
        replay_store = RawStore(self.settings.raw_dir, run_id)
        try:
            self._process(summary, replay_store, names, publish)
        except Exception as exc:
            self._fail(summary, exc)
            raise
        return summary

    def _process(self, summary: RunSummary, store: RawStore, names: list[str], publish: bool) -> None:
        records: list[RawRecord] = []
        for source in self._sources(names):
            parsed = [r for ref, content in store.documents(source.name) for r in source.parse(ref, content)]
            summary.extracted_by_source[source.name] = len(parsed)
            records += parsed

        result = transform(records)
        summary.transform = result
        self.repo.save_rejections(summary.run_id, result.rejections)
        summary.load = self.repo.upsert_rates(summary.run_id, result.rates)
        summary.moves = self.repo.biggest_moves(summary.run_id)

        if publish:
            publisher = self._publisher or self._default_publisher()
            if publisher:
                summary.publish = publisher.publish(result.rates)

        summary.status = "succeeded"
        self._finish(summary)

    def _sources(self, names: list[str]) -> list[Source]:
        s = self.settings
        return build_sources(names, s.source_base_url, s.mcl_mode, s.browser_channel, s.user_agent)

    def _default_publisher(self) -> LogisticsPublisher | None:
        s = self.settings
        if not (s.logistics_api_url and s.logistics_api_key):
            log.info("publishing skipped: FREIGHT_LOGISTICS_API_URL / _KEY not set")
            return None
        return LogisticsPublisher(
            str(s.logistics_api_url), s.logistics_api_key.get_secret_value(), s.publish_batch_size
        )

    def _fail(self, summary: RunSummary, exc: Exception) -> None:
        summary.status = "failed"
        summary.error = f"{type(exc).__name__}: {exc}"
        log.exception("run failed", extra={"run_id": summary.run_id})
        self._finish(summary)
        if self.settings.slack_webhook_url:
            send_alert(
                self.settings.slack_webhook_url.get_secret_value(),
                f":rotating_light: Freight rate run {summary.run_id} failed: {summary.error}",
            )

    def _finish(self, summary: RunSummary) -> None:
        t, ld, pub, f = summary.transform, summary.load, summary.publish, summary.fetch
        self.repo.finish_run(
            summary.run_id,
            summary.status,
            extracted=summary.extracted,
            valid=len(t.rates) if t else 0,
            rejected=len(t.rejections) if t else 0,
            duplicates=t.duplicates if t else 0,
            inserted=ld.inserted if ld else 0,
            updated=ld.updated if ld else 0,
            unchanged=ld.unchanged if ld else 0,
            published=pub.sent if pub else 0,
            publish_rejected=len(pub.rejected) if pub else 0,
            http_requests=f.requests if f else 0,
            http_retries=f.retries if f else 0,
            error=summary.error,
        )
        report_path = Path(self.settings.report_dir) / f"{summary.run_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render(summary), encoding="utf-8")
        log.info("run finished", extra={"run_id": summary.run_id, "status": summary.status, "report": str(report_path)})
