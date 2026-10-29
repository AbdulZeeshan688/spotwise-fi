"""Builders for quality-check test data."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from spotwise.ingest.sources.base import PriceSlot
from spotwise.timeutils import iter_market_slots, local_day_bounds_utc

HEL = ZoneInfo("Europe/Helsinki")


def day_rows(day: date, price: Callable[[int], str] = lambda i: "50") -> list[PriceSlot]:
    """One row per market slot of a Helsinki day; `price(i)` gives the i-th slot's price."""
    start, end = local_day_bounds_utc(day, HEL)
    return [
        PriceSlot(ts, res, Decimal(price(i)))
        for i, (ts, res) in enumerate(iter_market_slots(start, end, HEL))
    ]


def at(local: str) -> datetime:
    """Aware datetime from a Helsinki-local ISO string, e.g. '2026-03-28T16:00'."""
    return datetime.fromisoformat(local).replace(tzinfo=HEL)
