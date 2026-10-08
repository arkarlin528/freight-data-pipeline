"""Table definitions (SQLAlchemy Core). Alembic migrations in migrations/ create them."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(20), nullable=False),  # running | succeeded | failed
    Column("sources", String(100), nullable=False),
    Column("extracted", Integer, nullable=False, server_default="0"),
    Column("valid", Integer, nullable=False, server_default="0"),
    Column("rejected", Integer, nullable=False, server_default="0"),
    Column("duplicates", Integer, nullable=False, server_default="0"),
    Column("inserted", Integer, nullable=False, server_default="0"),
    Column("updated", Integer, nullable=False, server_default="0"),
    Column("unchanged", Integer, nullable=False, server_default="0"),
    Column("published", Integer, nullable=False, server_default="0"),
    Column("publish_rejected", Integer, nullable=False, server_default="0"),
    Column("http_requests", Integer, nullable=False, server_default="0"),
    Column("http_retries", Integer, nullable=False, server_default="0"),
    Column("error", Text),
)

# Current price per natural key. Re-running a crawl updates in place instead of adding rows.
freight_rates = Table(
    "freight_rates",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("carrier", String(10), nullable=False),
    Column("origin", String(5), nullable=False),
    Column("destination", String(5), nullable=False),
    Column("container_type", String(10), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount", Numeric(12, 2), nullable=False),
    Column("first_seen_run", UUID(as_uuid=False), ForeignKey("pipeline_runs.id"), nullable=False),
    Column("last_seen_run", UUID(as_uuid=False), ForeignKey("pipeline_runs.id"), nullable=False),
    Column("last_changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("carrier", "origin", "destination", "container_type", "valid_from", name="uq_freight_rates_key"),
    Index("ix_freight_rates_lane", "origin", "destination"),
)

# Append-only: one row whenever a price is first seen or changes. Powers "biggest movers" and trends.
rate_history = Table(
    "rate_history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("rate_id", BigInteger, ForeignKey("freight_rates.id", ondelete="CASCADE"), nullable=False),
    Column("run_id", UUID(as_uuid=False), ForeignKey("pipeline_runs.id"), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount", Numeric(12, 2), nullable=False),
    Column("previous_amount", Numeric(12, 2)),
    Column("observed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_rate_history_rate", "rate_id", "observed_at"),
)

# Rows that failed validation, with the reason and the raw values, for the data-quality report.
rejected_rows = Table(
    "rejected_rows",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", UUID(as_uuid=False), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
    Column("source", String(10), nullable=False),
    Column("ref", String(200), nullable=False),
    Column("reason", Text, nullable=False),
    Column("raw", JSONB, nullable=False),
    Index("ix_rejected_rows_run", "run_id"),
)
