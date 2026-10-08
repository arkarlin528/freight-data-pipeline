# ADR-0002: Keep every raw response; make runs replayable

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
Parsers break: a carrier renames a column, or a parser bug mis-reads a date. When that happens we want to fix the parser and **re-process the exact documents we saw**, without crawling the carriers again (which may have changed since, and costs them load).

## Decision
- Extraction is split into **fetch** (network → raw zone) and **parse** (bytes → records).
- The raw zone layout is `<raw_dir>/<run_id>/<source>/<document>` (e.g. `asl/page-2.html`). This is local disk here; the same keys map 1:1 to S3.
- `freight replay <run-id>` re-parses a run's raw files into a **new** run record, so history stays honest.
- Every record keeps its **source reference** (`asl/page-2.html#row-14`), and rejections and conflicts point back to it.

## Consequences
- ✅ Parser fixes are verified on real data, offline. There's a test that replays with the network unreachable.
- ✅ Debugging "why is this price wrong?" starts from the exact bytes we received.
- ⚠️ Storage grows (~40 KB a run here). Use a lifecycle rule, e.g. keep 90 days, then archive to S3 Glacier.
