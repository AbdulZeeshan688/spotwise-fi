"""Timezone and DST helpers. The DB is UTC; "days" are Helsinki-local days."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from spotwise.config import get_settings

# The Nordic day-ahead market moved to 15-minute prices for delivery from this
# Helsinki-local day onwards (checked against porssisahko.net data). Older days are hourly.
FIFTEEN_MINUTE_START_DAY = date(2025, 10, 1)


def local_tz() -> ZoneInfo:
    """The local market timezone from config (Europe/Helsinki by default)."""
    return ZoneInfo(get_settings().timezone)


def local_today(now: datetime | None = None, tz: ZoneInfo | None = None) -> date:
    """Today's date in the local timezone. Pass `now` to freeze the clock in tests."""
    tz = tz or local_tz()
    return (now or datetime.now(UTC)).astimezone(tz).date()


def local_day_bounds_utc(day: date, tz: ZoneInfo | None = None) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of a local day. Length is 23, 24 or 25 h."""
    tz = tz or local_tz()
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def resolution_for_day(day: date) -> int:
    """Market resolution in minutes for a local day: 15 from Oct 2025, 60 before."""
    return 15 if day >= FIFTEEN_MINUTE_START_DAY else 60


def expected_slot_count(day: date, resolution_minutes: int, tz: ZoneInfo | None = None) -> int:
    """How many slots a local day has, e.g. 23/24/25 hourly or 92/96/100 quarters."""
    start, end = local_day_bounds_utc(day, tz)
    return (end - start) // timedelta(minutes=resolution_minutes)


def iter_market_slots(
    start: datetime, end: datetime, tz: ZoneInfo | None = None
) -> Iterator[tuple[datetime, int]]:
    """Yield (UTC slot start, resolution) for every market slot in [start, end).

    `start` must be on a full hour. The step follows `resolution_for_day`, so a range
    that crosses the 15-minute switch yields hourly slots first, then quarters.
    """
    tz = tz or local_tz()
    ts = start.astimezone(UTC)
    while ts < end:
        resolution = resolution_for_day(ts.astimezone(tz).date())
        yield ts, resolution
        ts += timedelta(minutes=resolution)
