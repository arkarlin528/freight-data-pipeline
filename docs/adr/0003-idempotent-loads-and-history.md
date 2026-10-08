# ADR-0003: Idempotent loads on a natural key, with an append-only price history

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
The pipeline runs daily and may be retried after a failure. Running it twice must not duplicate rates. People also want to know *what changed*: which lanes moved, by how much, since when.

## Decision
- **Natural key:** `(carrier, origin, destination, container_type, valid_from)`. It has a unique constraint in PostgreSQL and is also used for in-batch duplicate detection.
- **Upsert:** `INSERT … ON CONFLICT ON CONSTRAINT uq_freight_rates_key DO UPDATE`, in one transaction per run. Each row ends up as **new**, **changed** (price, currency or end date differs) or **unchanged** (only `last_seen_run` moves).
- **`rate_history`** is append-only: a row on first sighting and on every change, with `previous_amount`. The report's *biggest price moves* comes from here.
- **Duplicates inside one crawl:** exact duplicates are dropped and counted; the same key with a *different* price is rejected as a conflict, pointing at the first row.
- **Run log:** `pipeline_runs` records counts, HTTP stats, status and error for every run, including failed ones.

## Consequences
- ✅ Proven by tests: run twice → 290 unchanged; market move → changes + matching history rows; offline replay → 290 unchanged. A live run recorded 66 changes.
- ✅ The downstream platform gets the same idempotency guarantee (its import is an upsert on the same key).
- ⚠️ Rows are upserted one by one (~300 a day, which is fine). For tens of thousands, switch to COPY into a staging table + one `MERGE`.
