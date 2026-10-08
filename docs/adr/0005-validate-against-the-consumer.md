# ADR-0005: Validate against the consumer's reference data, and report instead of drop

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
The rates feed the logistics platform (project #1), which only knows certain port codes, carriers and container types. Bad rows exist in every source: "On request" prices, unknown ports, unsupported equipment, reversed dates, zero prices.

## Decision
- **Normalise per source, validate once:** each source has a small mapper (port *names* → UN/LOCODE, `40' High Cube`/`40'HC` → `40HC`, `USD 1,250.00` / cents / `1.234,50` → `Decimal`). A single Pydantic `Rate` model then enforces the shared rules.
- **Reference data mirrors the consumer:** `reference.py` holds the platform's ports, carriers and container types, so a row the platform would reject is rejected **here**, with a clear reason, before publishing.
- **Nothing disappears silently:** every record becomes a `Rate` or a `Rejection(reason, raw values, source ref)`. Rejections are stored in `rejected_rows` and grouped in the run report.
- **Publishing** sends batches (≤1000, the platform's limit) to `POST /api/rates/import` with `X-Api-Key`. The platform's partial-success response is mapped back to source refs. Retrying a batch is safe because the import is idempotent.

## Consequences
- ✅ In the live integration run, 290 rates were published and **0 were rejected by the platform**: all 11 bad rows were caught upstream with reasons.
- ✅ Money stays `Decimal` until the JSON boundary.
- ⚠️ The reference lists are duplicated from the platform. Syncing from `GET /api/reference/ports` would remove that; it's on the roadmap.
