"""The frozen eval data: 60 days of real FI prices plus a frozen clock."""

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from spotwise.prices.slot import PriceSlot

FIXTURE_CSV = Path(__file__).parent / "prices_fi.csv"
FIRST_DAY = date(2025, 9, 17)
LAST_DAY = date(2025, 11, 15)
# Saturday morning, before the next day's prices are published (see EVAL_SEED_QUESTIONS.md)
EVAL_NOW = datetime(2025, 11, 15, 10, 0, tzinfo=ZoneInfo("Europe/Helsinki"))


@dataclass(frozen=True)
class FixtureRow:
    slot: PriceSlot
    source: str


@lru_cache
def load_fixture(path: Path = FIXTURE_CSV) -> tuple[FixtureRow, ...]:
    """All fixture rows, sorted by time."""
    with path.open() as f:
        rows = [
            FixtureRow(
                PriceSlot(
                    datetime.fromisoformat(r["ts_start"]).astimezone(UTC),
                    int(r["resolution_minutes"]),
                    Decimal(r["price_eur_mwh"]),
                ),
                r["source"],
            )
            for r in csv.DictReader(f)
        ]
    return tuple(sorted(rows, key=lambda r: r.slot.ts_start))


def fixture_slots(start: datetime, end: datetime) -> list[PriceSlot]:
    """Fixture slots with ts_start in [start, end), like db.queries.load_slots."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    return [r.slot for r in load_fixture() if start <= r.slot.ts_start < end]
