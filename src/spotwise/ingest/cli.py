"""Ingestion CLI: `python -m spotwise.ingest.cli backfill --days 730`, `daily` or `quality`."""

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import httpx
import typer
from sqlalchemy.orm import Session

from spotwise.config import get_settings
from spotwise.db.session import get_engine
from spotwise.ingest.pipeline import build_sources, run_ingestion
from spotwise.quality.report import run_quality_checks
from spotwise.timeutils import local_today

logger = logging.getLogger(__name__)
app = typer.Typer(help="Fetch Finnish day-ahead prices into the database.", no_args_is_help=True)


@app.callback()
def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.command()
def backfill(
    days: int = typer.Option(..., min=1, help="How many days back from today to fetch."),
) -> None:
    """Fetch the last N days of prices (safe to re-run)."""
    today = local_today()
    _ingest(today - timedelta(days=days), today, check_quality=False)


@app.command()
def daily() -> None:
    """Fetch today and tomorrow, then run the data-quality checks."""
    today = local_today()
    _ingest(today, today + timedelta(days=1), check_quality=True)


@app.command()
def quality(
    days: int = typer.Option(1, min=0, help="Also check this many days before today."),
) -> None:
    """Run the data-quality checks without fetching anything."""
    settings = get_settings()
    with Session(get_engine()) as session:
        run_quality_checks(
            session, settings.price_area, ZoneInfo(settings.timezone), days_back=days
        )


def _ingest(date_from: date, date_to: date, check_quality: bool) -> None:
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    headers = {"User-Agent": "spotwise-fi/0.1 (portfolio project)"}
    with httpx.Client(timeout=60, headers=headers) as client, Session(get_engine()) as session:
        result = run_ingestion(
            session, build_sources(settings, client), date_from, date_to, settings.price_area, tz
        )
        if check_quality:
            # Run even after a failed ingestion: the checks show what is missing.
            run_quality_checks(session, settings.price_area, tz)
    if result.status != "success":
        # Non-zero exit so cron jobs and CI show the run as failed.
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
