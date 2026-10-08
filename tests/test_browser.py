"""
Renders the JavaScript carrier page with a real browser. Needs a running mock site and Playwright:

    FREIGHT_TEST_LIVE_URL=http://127.0.0.1:8900 FREIGHT_TEST_BROWSER_CHANNEL=msedge pytest -m browser
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from freight_pipeline.extract.http import PoliteClient
from freight_pipeline.extract.raw_store import RawStore
from freight_pipeline.extract.sources import MclSource

pytestmark = pytest.mark.browser

LIVE_URL = os.getenv("FREIGHT_TEST_LIVE_URL")


@pytest.mark.skipif(not LIVE_URL, reason="set FREIGHT_TEST_LIVE_URL to a running mock site")
def test_browser_mode_sees_the_same_rates_as_the_api(tmp_path: Path) -> None:
    assert LIVE_URL is not None
    channel = os.getenv("FREIGHT_TEST_BROWSER_CHANNEL") or None
    client = PoliteClient("TestBot/1.0", min_interval=0, honour_crawl_delay=False)
    via_api, via_browser = RawStore(tmp_path, "api"), RawStore(tmp_path, "browser")

    MclSource(LIVE_URL, mode="api").fetch(client, via_api)
    MclSource(LIVE_URL, mode="browser", browser_channel=channel).fetch(client, via_browser)

    source = MclSource(LIVE_URL)
    api_rows = [r.fields for ref, raw in via_api.documents("mcl") for r in source.parse(ref, raw)]
    browser_rows = [r.fields for ref, raw in via_browser.documents("mcl") for r in source.parse(ref, raw)]
    assert len(browser_rows) == 100
    assert browser_rows == api_rows
