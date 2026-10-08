"""
A polite HTTP client for crawling: identifies itself, obeys robots.txt (including Crawl-delay),
spaces requests out per host, and retries transient failures with exponential backoff and jitter,
honouring Retry-After. Permanent failures (404, robots disallow) are not retried.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class DisallowedByRobots(Exception):
    pass


class RetryableHttpError(Exception):
    def __init__(self, response: httpx.Response):
        super().__init__(f"{response.status_code} from {response.request.url}")
        self.response = response


@dataclass
class FetchStats:
    requests: int = 0
    retries: int = 0
    bytes: int = 0
    by_status: dict[int, int] = field(default_factory=dict)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableHttpError | httpx.TransportError)


def _wait(state: RetryCallState) -> float:
    """Retry-After if the server sent one, otherwise exponential backoff with jitter."""
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, RetryableHttpError):
        retry_after = exc.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 60.0)
    return wait_exponential_jitter(initial=0.5, max=20)(state)


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        timeout: float = 15.0,
        max_attempts: int = 4,
        client: httpx.Client | None = None,
        honour_crawl_delay: bool = True,
    ):
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._client.headers["User-Agent"] = user_agent
        self._user_agent = user_agent
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()
        self._honour_crawl_delay = honour_crawl_delay
        self.stats = FetchStats()

    def get(self, url: str) -> httpx.Response:
        self._check_robots(url)

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._max_attempts),
            wait=_wait,
            reraise=True,
            before_sleep=self._on_retry,
        )
        def attempt() -> httpx.Response:
            self._throttle(url)
            response = self._client.get(url)
            self.stats.requests += 1
            self.stats.by_status[response.status_code] = self.stats.by_status.get(response.status_code, 0) + 1
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableHttpError(response)
            response.raise_for_status()  # 4xx other than 429: a real error, not worth retrying
            self.stats.bytes += len(response.content)
            return response

        return attempt()

    def close(self) -> None:
        self._client.close()

    def _on_retry(self, state: RetryCallState) -> None:
        self.stats.retries += 1
        exc = state.outcome.exception() if state.outcome else None
        log.warning("retrying after transient failure", extra={"attempt": state.attempt_number, "error": str(exc)})

    def _host(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _check_robots(self, url: str) -> None:
        host = self._host(url)
        parser = self._robots.get(host)
        if parser is None:
            parser = RobotFileParser()
            try:
                response = self._client.get(urljoin(host, "/robots.txt"))
                parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])  # unreachable robots.txt: treat as allow-all, like most crawlers
            self._robots[host] = parser
        if not parser.can_fetch(self._user_agent, url):
            raise DisallowedByRobots(f"robots.txt disallows {url}")

    def _throttle(self, url: str) -> None:
        host = self._host(url)
        robots = self._robots.get(host)
        crawl_delay = float((robots and robots.crawl_delay(self._user_agent)) or 0) if self._honour_crawl_delay else 0.0
        delay = max(self._min_interval, crawl_delay)
        with self._lock:
            wait = self._last_request.get(host, 0.0) + delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()
