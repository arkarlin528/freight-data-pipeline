"""
Pushes rates to the logistics platform (project #1): POST /api/rates/import with X-Api-Key.

The endpoint is an idempotent upsert on the natural key and reports bad rows instead of failing the
batch (see that project's ADR-0006). So retrying a whole batch after a timeout is always safe, and
rows the platform rejects are counted and logged rather than stopping the run.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from freight_pipeline.models import Rate

log = logging.getLogger(__name__)

SOURCE_NAME = "freight-data-pipeline"


@dataclass
class PublishResult:
    sent: int = 0
    inserted: int = 0
    updated: int = 0
    rejected: list[str] = field(default_factory=list)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {429, 500, 502, 503, 504}


class LogisticsPublisher:
    MAX_BATCH = 1000  # the platform's documented limit

    def __init__(self, base_url: str, api_key: str, batch_size: int = 500, client: httpx.Client | None = None):
        self._client = client or httpx.Client(base_url=base_url, timeout=30)
        self._api_key = api_key
        self._batch_size = min(batch_size, self.MAX_BATCH)

    def publish(self, rates: list[Rate]) -> PublishResult:
        result = PublishResult()
        for batch in _batches(rates, self._batch_size):
            body = self._send(batch)
            result.sent += len(batch)
            result.inserted += int(body.get("inserted", 0))
            result.updated += int(body.get("updated", 0))
            for rejection in body.get("rejected", []):
                row = batch[int(rejection["row"])]
                result.rejected.append(f"{row.source_ref}: {rejection['reason']}")
        if result.rejected:
            log.warning(
                "platform rejected rows", extra={"count": len(result.rejected), "examples": result.rejected[:3]}
            )
        return result

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=15),
        reraise=True,
    )
    def _send(self, batch: list[Rate]) -> dict[str, Any]:
        response = self._client.post(
            "/api/rates/import",
            headers={"X-Api-Key": self._api_key},
            json={
                "source": SOURCE_NAME,
                "rates": [
                    {
                        "origin": r.origin,
                        "destination": r.destination,
                        "carrierCode": r.carrier,
                        "containerType": r.container_type,
                        "currency": r.currency,
                        "amount": float(r.amount),
                        "validFrom": r.valid_from.isoformat(),
                        "validTo": r.valid_to.isoformat(),
                    }
                    for r in batch
                ],
            },
        )
        response.raise_for_status()
        return dict(response.json())

    def close(self) -> None:
        self._client.close()


def _batches(items: list[Rate], size: int) -> Iterator[list[Rate]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
