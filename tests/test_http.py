import httpx
import pytest
import respx

from freight_pipeline.extract.http import DisallowedByRobots, PoliteClient, RetryableHttpError

BASE = "https://carrier.example"
ROBOTS = "User-agent: *\nDisallow: /private/\nCrawl-delay: 1\n"


def _client(attempts: int = 3) -> PoliteClient:
    return PoliteClient("TestBot/1.0", min_interval=0, max_attempts=attempts, honour_crawl_delay=False)


@respx.mock
def test_retries_transient_errors_then_succeeds() -> None:
    respx.get(f"{BASE}/robots.txt").respond(200, text=ROBOTS)
    route = respx.get(f"{BASE}/rates").mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "0"}),
            httpx.ConnectError("connection reset"),
            httpx.Response(200, text="ok"),
        ]
    )
    client = _client()

    response = client.get(f"{BASE}/rates")

    assert response.text == "ok"
    assert route.call_count == 3
    assert client.stats.retries == 2
    assert client.stats.by_status == {503: 1, 200: 1}


@respx.mock
def test_gives_up_after_max_attempts() -> None:
    respx.get(f"{BASE}/robots.txt").respond(404)
    respx.get(f"{BASE}/rates").respond(503, headers={"Retry-After": "0"})

    with pytest.raises(RetryableHttpError):
        _client(attempts=2).get(f"{BASE}/rates")


@respx.mock
def test_client_errors_are_not_retried() -> None:
    respx.get(f"{BASE}/robots.txt").respond(404)
    route = respx.get(f"{BASE}/missing").respond(404)

    with pytest.raises(httpx.HTTPStatusError):
        _client().get(f"{BASE}/missing")
    assert route.call_count == 1


@respx.mock
def test_obeys_robots_txt() -> None:
    respx.get(f"{BASE}/robots.txt").respond(200, text=ROBOTS)
    private = respx.get(f"{BASE}/private/prices")

    with pytest.raises(DisallowedByRobots):
        _client().get(f"{BASE}/private/prices")
    assert not private.called


@respx.mock
def test_identifies_itself() -> None:
    respx.get(f"{BASE}/robots.txt").respond(404)
    route = respx.get(f"{BASE}/rates").respond(200)

    _client().get(f"{BASE}/rates")

    assert route.calls.last.request.headers["User-Agent"] == "TestBot/1.0"


@respx.mock
def test_spaces_requests_using_crawl_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(f"{BASE}/robots.txt").respond(200, text=ROBOTS)
    respx.get(f"{BASE}/a").respond(200)
    sleeps: list[float] = []
    monkeypatch.setattr("freight_pipeline.extract.http.time.sleep", sleeps.append)
    client = PoliteClient("TestBot/1.0", min_interval=0, max_attempts=1)  # honours Crawl-delay: 1

    client.get(f"{BASE}/a")
    client.get(f"{BASE}/a")

    assert len(sleeps) == 1 and 0.9 < sleeps[0] <= 1.0
