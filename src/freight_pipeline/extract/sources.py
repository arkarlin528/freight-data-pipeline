"""
One class per carrier. Each separates *fetching* (network, saved to the raw zone) from *parsing*
(pure, from bytes), so parsing can be unit-tested on fixtures and re-run on old raw files.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import ClassVar, Protocol
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from freight_pipeline.extract.http import PoliteClient
from freight_pipeline.extract.raw_store import RawStore
from freight_pipeline.models import RawRecord

log = logging.getLogger(__name__)


class Source(Protocol):
    name: ClassVar[str]

    def fetch(self, client: PoliteClient, store: RawStore) -> None: ...

    def parse(self, ref: str, content: bytes) -> list[RawRecord]: ...


class AslHtmlSource:
    """Andaman Sea Lines: server-rendered HTML table, follows 'Next' links until the last page."""

    name: ClassVar[str] = "asl"
    MAX_PAGES = 50  # safety stop if pagination ever loops

    def __init__(self, base_url: str):
        self.start_url = urljoin(base_url, "/asl/tariffs")

    def fetch(self, client: PoliteClient, store: RawStore) -> None:
        url: str | None = self.start_url
        page = 1
        while url and page <= self.MAX_PAGES:
            response = client.get(url)
            store.save(self.name, f"page-{page}.html", response.content)
            next_link = BeautifulSoup(response.content, "lxml").select_one("a.next[href]")
            url = urljoin(url, str(next_link["href"])) if next_link else None
            page += 1

    def parse(self, ref: str, content: bytes) -> list[RawRecord]:
        soup = BeautifulSoup(content, "lxml")
        records = []
        for i, row in enumerate(soup.select("table#tariffs tbody tr"), start=1):
            cells = {_first_class(cell): cell.get_text(" ", strip=True) for cell in row.find_all("td")}
            records.append(
                RawRecord(
                    self.name,
                    f"{ref}#row-{i}",
                    {
                        "from": cells.get("pol", ""),
                        "to": cells.get("pod", ""),
                        "equipment": cells.get("eqp", ""),
                        "rate": cells.get("rate", ""),
                        "validity": cells.get("validity", ""),
                    },
                )
            )
        if not records:
            log.warning("no rows found: page layout may have changed", extra={"ref": ref})
        return records


def _first_class(cell: Tag) -> str:
    classes = cell.get("class")
    return str(classes[0]) if isinstance(classes, list) and classes else ""


class MclSource:
    """
    Mekong Container Lines: a JavaScript app. Default mode reads the JSON API the page itself calls
    (faster, stable, fewer moving parts). "browser" mode renders the page with Playwright, for sites
    where the data is only available after scripts run.
    """

    name: ClassVar[str] = "mcl"

    def __init__(self, base_url: str, mode: str = "api", browser_channel: str | None = None, user_agent: str = ""):
        self.base_url = base_url
        self.mode = mode
        self.browser_channel = browser_channel
        self.user_agent = user_agent

    def fetch(self, client: PoliteClient, store: RawStore) -> None:
        if self.mode == "browser":
            rates = self._render_with_browser()
            store.save(self.name, "rates.json", json.dumps({"rates": rates}).encode())
        else:
            response = client.get(urljoin(self.base_url, "/mcl/api/rates"))
            store.save(self.name, "rates.json", response.content)

    def _render_with_browser(self) -> list[dict[str, object]]:
        from playwright.sync_api import sync_playwright  # optional dependency: freight-pipeline[browser]

        with sync_playwright() as p:
            browser = p.chromium.launch(channel=self.browser_channel, headless=True)
            try:
                page = browser.new_page(user_agent=self.user_agent or None)
                page.goto(urljoin(self.base_url, "/mcl/rates"))
                page.wait_for_selector("#rates tbody tr", timeout=15_000)
                rows: list[str] = page.eval_on_selector_all("#rates tbody tr", "rows => rows.map(r => r.dataset.rate)")
                return [json.loads(row) for row in rows]
            finally:
                browser.close()

    def parse(self, ref: str, content: bytes) -> list[RawRecord]:
        payload = json.loads(content)
        return [
            RawRecord(self.name, f"{ref}#item-{i}", {k: str(v) for k, v in item.items()})
            for i, item in enumerate(payload.get("rates", []), start=1)
        ]


class SscCsvSource:
    """Straits Shipping Co.: a semicolon-separated CSV export with comma decimals."""

    name: ClassVar[str] = "ssc"

    def __init__(self, base_url: str):
        self.url = urljoin(base_url, "/ssc/rates.csv")

    def fetch(self, client: PoliteClient, store: RawStore) -> None:
        store.save(self.name, "rates.csv", client.get(self.url).content)

    def parse(self, ref: str, content: bytes) -> list[RawRecord]:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        return [
            RawRecord(self.name, f"{ref}#line-{i}", {k: (v or "") for k, v in row.items() if k})
            for i, row in enumerate(reader, start=2)  # line 1 is the header
        ]


def build_sources(
    names: list[str], base_url: str, mcl_mode: str = "api", browser_channel: str | None = None, user_agent: str = ""
) -> list[Source]:
    available: dict[str, Source] = {
        "asl": AslHtmlSource(base_url),
        "mcl": MclSource(base_url, mcl_mode, browser_channel, user_agent),
        "ssc": SscCsvSource(base_url),
    }
    unknown = set(names) - available.keys()
    if unknown:
        raise ValueError(f"unknown sources: {', '.join(sorted(unknown))}")
    return [available[n] for n in names]
