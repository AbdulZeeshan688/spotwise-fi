from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from spotwise.tools.periods import PeriodError, resolve_period

HEL = ZoneInfo("Europe/Helsinki")
NOW = datetime(2026, 10, 29, 10, 40, tzinfo=HEL)  # a Thursday


def iso(text: str) -> tuple[str, str]:
    period = resolve_period(text, NOW, HEL)
    return period.start.isoformat(), period.end.isoformat()


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("today", "2026-10-29T00:00:00+02:00", "2026-10-30T00:00:00+02:00"),
        ("Tomorrow", "2026-10-30T00:00:00+02:00", "2026-10-31T00:00:00+02:00"),
        ("yesterday", "2026-10-28T00:00:00+02:00", "2026-10-29T00:00:00+02:00"),
        ("this week", "2026-10-26T00:00:00+02:00", "2026-11-02T00:00:00+02:00"),
        ("last week", "2026-10-19T00:00:00+03:00", "2026-10-26T00:00:00+02:00"),
        ("4 weeks ago", "2026-09-28T00:00:00+03:00", "2026-10-05T00:00:00+03:00"),
        ("this month", "2026-10-01T00:00:00+03:00", "2026-11-01T00:00:00+02:00"),
        ("last month", "2026-09-01T00:00:00+03:00", "2026-10-01T00:00:00+03:00"),
        ("1 month ago", "2026-09-01T00:00:00+03:00", "2026-10-01T00:00:00+03:00"),
        ("3 days ago", "2026-10-26T00:00:00+02:00", "2026-10-27T00:00:00+02:00"),
        ("last 7 days", "2026-10-23T00:00:00+03:00", "2026-10-30T00:00:00+02:00"),
        ("2026-10-01", "2026-10-01T00:00:00+03:00", "2026-10-02T00:00:00+03:00"),
        ("2026-10-01..2026-10-03", "2026-10-01T00:00:00+03:00", "2026-10-04T00:00:00+03:00"),
        ("2026-02", "2026-02-01T00:00:00+02:00", "2026-03-01T00:00:00+02:00"),
        ("today 22:00-06:00", "2026-10-29T22:00:00+02:00", "2026-10-30T06:00:00+02:00"),
        ("tomorrow 08:00 - 12:30", "2026-10-30T08:00:00+02:00", "2026-10-30T12:30:00+02:00"),
        ("next 2 hours", "2026-10-29T10:30:00+02:00", "2026-10-29T12:30:00+02:00"),
    ],
)
def test_resolve_period(text: str, start: str, end: str) -> None:
    assert iso(text) == (start, end)


def test_last_week_over_dst_change_is_169_hours() -> None:
    period = resolve_period("last week", NOW, HEL)
    # Subtract in UTC: Python subtracts same-zone datetimes as wall-clock time (168 h)
    elapsed = period.end.astimezone(ZoneInfo("UTC")) - period.start.astimezone(ZoneInfo("UTC"))
    assert elapsed.total_seconds() / 3600 == 169  # DST ended Sunday 25 Oct


def test_next_hours_across_dst_uses_real_hours() -> None:
    before_dst_end = datetime(2026, 10, 25, 2, 0, tzinfo=HEL)  # 02:00 at UTC+3
    period = resolve_period("next 3 hours", before_dst_end, HEL)
    elapsed = period.end.astimezone(ZoneInfo("UTC")) - period.start.astimezone(ZoneInfo("UTC"))
    assert elapsed.total_seconds() == 3 * 3600
    assert period.end.isoformat() == "2026-10-25T04:00:00+02:00"


def test_month_ago_across_year() -> None:
    january = datetime(2026, 1, 15, 12, tzinfo=HEL)
    assert (
        resolve_period("last month", january, HEL).start.isoformat() == "2025-12-01T00:00:00+02:00"
    )


@pytest.mark.parametrize(
    "text",
    [
        "next friday",
        "2026-13",
        "today 22:10-23:00",
        "today 25:00-26:00",
        "2026-10-05..2026-10-01",
        "last 0 days",
    ],
)
def test_bad_periods_raise_helpful_error(text: str) -> None:
    with pytest.raises(PeriodError):
        resolve_period(text, NOW, HEL)


def test_error_lists_supported_formats() -> None:
    with pytest.raises(PeriodError, match="Supported:"):
        resolve_period("whenever", NOW, HEL)
