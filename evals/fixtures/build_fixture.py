"""Build the frozen eval fixture: real FI prices for a fixed date range, as CSV.

Run once and commit the CSV; evals must never depend on live data.
    uv run python -m evals.fixtures.build_fixture --start 2025-09-17 --end 2025-11-15

Resumable: days already in the CSV are skipped, so an interrupted run can continue.
Uses ENTSO-E when ENTSOE_TOKEN is set, otherwise porssisahko.net (slow: one request
per slot, about 35 minutes for 60 days).
"""

import csv
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import httpx
import typer

from evals.fixtures.fixture import FIXTURE_CSV
from spotwise.config import get_settings
from spotwise.ingest.normalise import normalise_slots
from spotwise.ingest.pipeline import build_sources
from spotwise.ingest.sources.base import Source, SourceError
from spotwise.timeutils import local_day_bounds_utc

COLUMNS = ["ts_start", "resolution_minutes", "price_eur_mwh", "source"]

logger = logging.getLogger(__name__)


def main(
    start: Annotated[str, typer.Option(help="First Helsinki day, YYYY-MM-DD")],
    end: Annotated[str, typer.Option(help="Last Helsinki day (inclusive), YYYY-MM-DD")],
    out: Annotated[Path, typer.Option(help="CSV file to write")] = FIXTURE_CSV,
) -> None:
    """Fetch every day in the range and append it to the CSV."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    done = _days_in_csv(out, tz)
    new_file = not out.exists()

    with httpx.Client(timeout=60) as client, out.open("a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(COLUMNS)
        sources = build_sources(settings, client)
        day = date.fromisoformat(start)
        while day <= date.fromisoformat(end):
            if day not in done:
                _fetch_day(day, tz, sources, writer)
                f.flush()  # keep finished days if the run is interrupted
            day += timedelta(days=1)


def _fetch_day(day: date, tz: ZoneInfo, sources: list[Source], writer: Any) -> None:
    """Fetch one day from the first source that works and write its rows."""
    day_start, day_end = local_day_bounds_utc(day, tz)
    for source in sources:
        try:
            slots = normalise_slots(source.fetch(day_start, day_end), day_start, day_end)
        except SourceError as exc:
            logger.warning("%s failed for %s: %s", source.name, day, exc)
            continue
        for s in slots:
            writer.writerow(
                [s.ts_start.isoformat(), s.resolution_minutes, s.price_eur_mwh, source.name]
            )
        logger.info("%s: %d slots from %s", day, len(slots), source.name)
        return
    logger.error("All sources failed for %s", day)
    raise typer.Exit(code=1)


def _days_in_csv(path: Path, tz: ZoneInfo) -> set[date]:
    if not path.exists():
        return set()
    with path.open() as f:
        rows = csv.DictReader(f)
        return {datetime.fromisoformat(row["ts_start"]).astimezone(tz).date() for row in rows}


if __name__ == "__main__":
    typer.run(main)
