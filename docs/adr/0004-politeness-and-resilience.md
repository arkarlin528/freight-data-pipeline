# ADR-0004: Crawl politely; recover from transient failures, stop on real ones

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
Carrier sites aren't ours. Hammering them gets us blocked (and is rude); being fragile gets us empty dashboards. Networks and servers fail transiently all the time.

## Decision
All HTTP goes through `PoliteClient` ([`extract/http.py`](../../src/freight_pipeline/extract/http.py)), which:
- **identifies itself** with a descriptive User-Agent and a contact URL;
- **obeys `robots.txt`**, including `Disallow` (raises `DisallowedByRobots`, never fetched) and `Crawl-delay`, and enforces a per-host minimum interval;
- **retries only what's worth retrying:**
  - transport errors and 429/500/502/503/504 are retried, with exponential backoff + jitter, and honour `Retry-After`;
  - other 4xx errors fail immediately.
- **counts** requests, retries, bytes and status codes into the run record and report.

When a run still fails, it's recorded as `failed` with the error, the report says why, an optional Slack alert fires, and the process exits non-zero (so cron/Lambda/CI see it).

## Consequences
- ✅ Tested:
  - retry after 503 and connection reset;
  - give up after N attempts;
  - no retry on 404;
  - robots disallow;
  - User-Agent;
  - Crawl-delay timing;
  - a whole run surviving a site that fails every 3rd request;
  - a run that runs out of retries is recorded as failed.
- ✅ The mock site can be made flaky (`MOCK_FLAKY_EVERY`) to demonstrate this live.
- ⚠️ This is only for sites whose terms allow automated access. The mock site exists so the portfolio never scrapes anyone else.
