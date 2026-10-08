from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from freight_pipeline.load.schema import freight_rates, pipeline_runs, rate_history, rejected_rows
from freight_pipeline.models import Rate, Rejection


@dataclass(frozen=True)
class LoadResult:
    inserted: int
    updated: int
    unchanged: int


@dataclass(frozen=True)
class PriceMove:
    carrier: str
    origin: str
    destination: str
    container_type: str
    previous: Decimal
    current: Decimal

    @property
    def change_pct(self) -> float:
        return float((self.current - self.previous) / self.previous * 100)


class Repository:
    def __init__(self, engine: Engine):
        self.engine = engine

    # --- runs ----------------------------------------------------------------------------------

    def start_run(self, run_id: str, sources: list[str]) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(pipeline_runs).values(id=run_id, status="running", sources=",".join(sources)))

    def finish_run(self, run_id: str, status: str, **counters: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.id == run_id)
                .values(status=status, finished_at=func.now(), **counters)
            )

    def last_successful_run_id(self) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                select(pipeline_runs.c.id)
                .where(pipeline_runs.c.status == "succeeded")
                .order_by(pipeline_runs.c.started_at.desc())
                .limit(1)
            ).scalar_one_or_none()

    # --- rates ---------------------------------------------------------------------------------

    def upsert_rates(self, run_id: str, rates: list[Rate]) -> LoadResult:
        """
        Idempotent load in one transaction. New key → insert. Same key with a different price or end
        date → update + history row. Same values → only last_seen_run moves. Safe to run twice.
        """
        inserted = updated = 0
        with self.engine.begin() as conn:
            existing = self._current_prices(conn, rates)
            for rate in rates:
                values = {
                    "carrier": rate.carrier,
                    "origin": rate.origin,
                    "destination": rate.destination,
                    "container_type": rate.container_type,
                    "valid_from": rate.valid_from,
                    "valid_to": rate.valid_to,
                    "currency": rate.currency,
                    "amount": rate.amount,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                }
                before = existing.get(rate.key)
                changed = before is None or before[1:] != (rate.amount, rate.currency, rate.valid_to)

                insert_stmt = pg_insert(freight_rates).values(**values)
                upsert = insert_stmt.on_conflict_do_update(
                    constraint="uq_freight_rates_key",
                    set_={
                        "valid_to": insert_stmt.excluded.valid_to,
                        "currency": insert_stmt.excluded.currency,
                        "amount": insert_stmt.excluded.amount,
                        "last_seen_run": insert_stmt.excluded.last_seen_run,
                        **({"last_changed_at": func.now()} if changed else {}),
                    },
                ).returning(freight_rates.c.id)
                rate_id = conn.execute(upsert).scalar_one()

                if before is None:
                    inserted += 1
                elif changed:
                    updated += 1
                if changed:
                    conn.execute(
                        insert(rate_history).values(
                            rate_id=rate_id,
                            run_id=run_id,
                            currency=rate.currency,
                            amount=rate.amount,
                            previous_amount=before[1] if before else None,
                        )
                    )

        return LoadResult(inserted, updated, len(rates) - inserted - updated)

    def _current_prices(
        self, conn: Connection, rates: list[Rate]
    ) -> dict[tuple[Any, ...], tuple[int, Decimal, str, Any]]:
        if not rates:
            return {}
        carriers = {r.carrier for r in rates}
        rows = conn.execute(
            select(
                freight_rates.c.id,
                freight_rates.c.carrier,
                freight_rates.c.origin,
                freight_rates.c.destination,
                freight_rates.c.container_type,
                freight_rates.c.valid_from,
                freight_rates.c.amount,
                freight_rates.c.currency,
                freight_rates.c.valid_to,
            ).where(freight_rates.c.carrier.in_(carriers))
        )
        return {
            (r.carrier, r.origin, r.destination, r.container_type, r.valid_from): (
                r.id,
                r.amount,
                r.currency,
                r.valid_to,
            )
            for r in rows
        }

    def save_rejections(self, run_id: str, rejections: list[Rejection]) -> None:
        if not rejections:
            return
        with self.engine.begin() as conn:
            conn.execute(
                insert(rejected_rows),
                [
                    {"run_id": run_id, "source": r.source, "ref": r.ref[:200], "reason": r.reason, "raw": r.raw}
                    for r in rejections
                ],
            )

    def biggest_moves(self, run_id: str, limit: int = 5) -> list[PriceMove]:
        """Price changes recorded in this run, largest relative change first."""
        h, r = rate_history, freight_rates
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(r.c.carrier, r.c.origin, r.c.destination, r.c.container_type, h.c.previous_amount, h.c.amount)
                .join(r, r.c.id == h.c.rate_id)
                .where(h.c.run_id == run_id, h.c.previous_amount.is_not(None))
                .order_by(func.abs((h.c.amount - h.c.previous_amount) / h.c.previous_amount).desc())
                .limit(limit)
            ).all()
        return [PriceMove(*row) for row in rows]
