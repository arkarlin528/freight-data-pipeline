# ADR-0001: Use the data API behind a page when there is one; render with a browser only when needed

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
Mekong Container Lines' rate page is a JavaScript app: the HTML is an empty shell, and the rates arrive from a JSON endpoint after the scripts run. Plain HTTP + HTML parsing sees nothing.

## Options considered
1. **Always use a headless browser (Playwright)** for every source: it works for anything, but it's slow (seconds per page), heavy (~500 MB image), and fragile (selectors, timing).
2. **Scrapy for everything:** a great framework for large crawls, but our three sources are a handful of documents a day, so its scheduler/middleware machinery is more than we need, and it still can't run JavaScript.
3. **Per source, use the simplest thing that works:**
   - plain HTTP for HTML and CSV;
   - the **JSON API the page itself calls** when there is one;
   - a browser only when the data exists only after rendering.

## Decision
**Option 3.** `MclSource` has two modes:
- `api` (default): call `/mcl/api/rates` directly. One request, structured data, nothing to render.
- `browser`: Playwright renders `/mcl/rates`, waits for the table, and reads the rows.

A test ([`test_browser.py`](../../tests/test_browser.py)) proves both modes return **identical rows**, so we can switch if the API ever disappears. Locally Playwright drives an installed browser (`FREIGHT_BROWSER_CHANNEL=msedge`); CI and Docker use Playwright's own Chromium image.

## Consequences
- ✅ A full run is 7 requests and a few seconds; the browser isn't on the hot path.
- ✅ The browser path stays tested, ready for sources that need it.
- ⚠️ Undocumented internal APIs can change without notice. That's mitigated by layout checks (zero rows → warning), the daily CI crawl, and the browser fallback.
