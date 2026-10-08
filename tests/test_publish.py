import json
from datetime import date
from decimal import Decimal

import httpx
import respx

from freight_pipeline.models import Rate
from freight_pipeline.publish.logistics import LogisticsPublisher

API = "http://logistics.test"


def _rate(i: int) -> Rate:
    return Rate(
        carrier="ASL",
        origin="THLCH",
        destination="SGSIN",
        container_type="20GP",
        currency="USD",
        amount=Decimal(100 + i),
        valid_from=date(2026, 10, i % 28 + 1),
        valid_to=date(2026, 12, 31),
        source_ref=f"asl/page-1.html#row-{i}",
    )


@respx.mock
def test_sends_batches_in_the_platform_format_and_sums_results() -> None:
    route = respx.post(f"{API}/api/rates/import").mock(
        side_effect=[
            httpx.Response(200, json={"inserted": 2, "updated": 0, "rejected": []}),
            httpx.Response(
                200, json={"inserted": 0, "updated": 1, "rejected": [{"row": 0, "reason": "Unknown carrier 'ASL'."}]}
            ),
        ]
    )
    publisher = LogisticsPublisher(API, "secret", batch_size=2)

    result = publisher.publish([_rate(1), _rate(2), _rate(3)])

    assert (result.sent, result.inserted, result.updated) == (3, 2, 1)
    assert result.rejected == ["asl/page-1.html#row-3: Unknown carrier 'ASL'."]
    first = route.calls[0].request
    assert first.headers["X-Api-Key"] == "secret"
    body = json.loads(first.content)
    assert body["source"] == "freight-data-pipeline"
    assert body["rates"][0] == {
        "origin": "THLCH",
        "destination": "SGSIN",
        "carrierCode": "ASL",
        "containerType": "20GP",
        "currency": "USD",
        "amount": 101.0,
        "validFrom": "2026-10-02",
        "validTo": "2026-12-31",
    }


@respx.mock
def test_retries_a_batch_after_a_server_error() -> None:
    # Safe because the platform's import is idempotent (upsert on the natural key).
    route = respx.post(f"{API}/api/rates/import").mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(200, json={"inserted": 1, "updated": 0, "rejected": []}),
        ]
    )

    result = LogisticsPublisher(API, "secret").publish([_rate(1)])

    assert route.call_count == 2 and result.inserted == 1


def test_never_exceeds_the_platform_batch_limit() -> None:
    assert LogisticsPublisher(API, "k", batch_size=5000)._batch_size == 1000
