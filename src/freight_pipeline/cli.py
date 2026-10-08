"""Command line: `freight run`, `freight replay <run-id>`, `freight runs`, `freight migrate`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import create_engine, select

from freight_pipeline import logging_setup
from freight_pipeline.config import get_settings
from freight_pipeline.load.schema import pipeline_runs
from freight_pipeline.pipeline import Pipeline
from freight_pipeline.report import RunSummary

app = typer.Typer(
    help="Freight rate pipeline: crawl carriers, validate, load to PostgreSQL, publish.", no_args_is_help=True
)


@app.callback()
def main(json_logs: Annotated[bool, typer.Option(help="JSON log lines (for servers)")] = False) -> None:
    logging_setup.configure(json_output=json_logs)


def _pipeline() -> Pipeline:
    settings = get_settings()
    return Pipeline(settings, create_engine(settings.database_url, pool_pre_ping=True))


def _print(summary: RunSummary) -> None:
    t, ld = summary.transform, summary.load
    typer.echo(f"run {summary.run_id}: {summary.status}")
    typer.echo(
        f"  extracted {summary.extracted}  valid {len(t.rates) if t else 0}  "
        f"rejected {len(t.rejections) if t else 0}  duplicates {t.duplicates if t else 0}"
    )
    if ld:
        typer.echo(f"  loaded: {ld.inserted} new, {ld.updated} changed, {ld.unchanged} unchanged")
    if summary.publish:
        typer.echo(f"  published {summary.publish.sent} ({len(summary.publish.rejected)} rejected by platform)")
    if summary.fetch:
        typer.echo(f"  http: {summary.fetch.requests} requests, {summary.fetch.retries} retries")
    typer.echo(f"  report: {Path(get_settings().report_dir) / (summary.run_id + '.md')}")


@app.command()
def run(
    source: Annotated[list[str] | None, typer.Option("--source", "-s", help="asl, mcl, ssc (default: all)")] = None,
    publish: Annotated[bool, typer.Option(help="Push valid rates to the logistics platform")] = True,
) -> None:
    """Crawl, validate, load and publish now."""
    _print(_pipeline().run(source, publish=publish))


@app.command()
def replay(run_id: str, publish: bool = False) -> None:
    """Re-process a previous run from its raw files, without crawling again."""
    _print(_pipeline().replay(run_id, publish=publish))


@app.command()
def runs(limit: int = 10) -> None:
    """Show recent runs."""
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        rows = conn.execute(select(pipeline_runs).order_by(pipeline_runs.c.started_at.desc()).limit(limit)).all()
    for r in rows:
        typer.echo(
            f"{r.started_at:%Y-%m-%d %H:%M}  {r.status:<9}  {r.id}  extracted={r.extracted} valid={r.valid} "
            f"rejected={r.rejected} new={r.inserted} changed={r.updated} published={r.published}"
        )


@app.command()
def migrate() -> None:
    """Create or upgrade the database schema (Alembic)."""
    from alembic import command
    from alembic.config import Config

    # Working directory first (Docker image: /app), then the source checkout.
    candidates = [Path.cwd() / "alembic.ini", Path(__file__).resolve().parents[2] / "alembic.ini"]
    ini = next((p for p in candidates if p.exists()), None)
    if ini is None:
        raise typer.BadParameter("alembic.ini not found; run from the project directory")
    config = Config(str(ini))
    config.set_main_option("script_location", str(ini.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")
    typer.echo("database is up to date")


if __name__ == "__main__":
    app()
