"""Turn words like "tomorrow" or "last week" into exact Helsinki time ranges.

This is deliberately code, not LLM: date math (week starts, month lengths, DST) is
easy to get wrong in text, and the agent must never guess it.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SUPPORTED_FORMATS = (
    "today, tomorrow, yesterday, this week, last week, this month, last month, "
    "N days ago, N weeks ago, N months ago, last N days, next N hours, "
    "YYYY-MM-DD, YYYY-MM-DD..YYYY-MM-DD, YYYY-MM, "
    "'<today|tomorrow|yesterday|YYYY-MM-DD> HH:MM-HH:MM' (end before start = next day)"
)

_TIME_RANGE = re.compile(
    r"^(today|tomorrow|yesterday|\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$"
)


@dataclass(frozen=True)
class Period:
    """A resolved time range: [start, end) in local time, plus a readable label."""

    start: datetime
    end: datetime
    label: str


class PeriodError(ValueError):
    """The period text could not be understood."""


def resolve_period(text: str, now: datetime, tz: ZoneInfo) -> Period:
    """Resolve a period description relative to `now` (weeks start on Monday)."""
    phrase = " ".join(text.lower().strip().split())
    today = now.astimezone(tz).date()

    if phrase == "today":
        return _days(today, today, "today", tz)
    if phrase == "tomorrow":
        day = today + timedelta(days=1)
        return _days(day, day, "tomorrow", tz)
    if phrase == "yesterday":
        day = today - timedelta(days=1)
        return _days(day, day, "yesterday", tz)
    if phrase == "this week":
        monday = today - timedelta(days=today.weekday())
        return _days(monday, monday + timedelta(days=6), "this week (Mon–Sun)", tz)
    if phrase == "last week":
        monday = today - timedelta(days=today.weekday() + 7)
        return _days(monday, monday + timedelta(days=6), "last week (Mon–Sun)", tz)
    if phrase == "this month":
        return _month(today.year, today.month, "this month", tz)
    if phrase == "last month":
        year, month = _shift_month(today.year, today.month, -1)
        return _month(year, month, "last month", tz)

    if match := re.fullmatch(r"(\d{1,3}) (day|week|month)s? ago", phrase):
        n, unit = int(match[1]), match[2]
        if unit == "day":
            day = today - timedelta(days=n)
            return _days(day, day, f"{n} days ago", tz)
        if unit == "week":
            monday = today - timedelta(days=today.weekday() + 7 * n)
            return _days(monday, monday + timedelta(days=6), f"{n} weeks ago (Mon–Sun)", tz)
        year, month = _shift_month(today.year, today.month, -n)
        return _month(year, month, f"{n} months ago", tz)

    if match := re.fullmatch(r"last (\d{1,3}) days", phrase):
        n = int(match[1])
        if n < 1:
            raise PeriodError("N must be at least 1")
        first = today - timedelta(days=n - 1)
        return _days(first, today, f"last {n} days (including today)", tz)

    if match := re.fullmatch(r"next (\d{1,2}) hours?", phrase):
        hours = int(match[1])
        if not 1 <= hours <= 48:
            raise PeriodError("next N hours: N must be 1..48")
        local_now = now.astimezone(tz)
        # Start at the beginning of the current 15-minute slot
        start = local_now.replace(
            minute=local_now.minute - local_now.minute % 15, second=0, microsecond=0
        )
        # Add in UTC: adding hours to a local time is wall-clock math and breaks on DST days
        end = (start.astimezone(UTC) + timedelta(hours=hours)).astimezone(tz)
        return Period(start, end, f"next {hours} hours")

    if match := _TIME_RANGE.fullmatch(phrase):
        return _time_range(match, today, tz)

    if match := re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", phrase):
        first, last = _parse_date(match[1]), _parse_date(match[2])
        if last < first:
            raise PeriodError("end date is before start date")
        return _days(first, last, f"{first} to {last}", tz)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phrase):
        day = _parse_date(phrase)
        return _days(day, day, str(day), tz)
    if match := re.fullmatch(r"(\d{4})-(\d{2})", phrase):
        year, month = int(match[1]), int(match[2])
        if not 1 <= month <= 12:
            raise PeriodError(f"bad month in {phrase!r}")
        return _month(year, month, phrase, tz)

    raise PeriodError(f"Unknown period {text!r}. Supported: {SUPPORTED_FORMATS}")


def _days(first: date, last: date, label: str, tz: ZoneInfo) -> Period:
    """Whole local days first..last (inclusive). Local midnights handle DST for us."""
    start = datetime.combine(first, time(0), tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), time(0), tzinfo=tz)
    return Period(start, end, label)


def _month(year: int, month: int, label: str, tz: ZoneInfo) -> Period:
    next_year, next_month = _shift_month(year, month, 1)
    last = date(next_year, next_month, 1) - timedelta(days=1)
    return _days(date(year, month, 1), last, label, tz)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _time_range(match: re.Match[str], today: date, tz: ZoneInfo) -> Period:
    day_word, h1, m1, h2, m2 = match.groups()
    offsets = {"today": 0, "tomorrow": 1, "yesterday": -1}
    day = (
        today + timedelta(days=offsets[day_word]) if day_word in offsets else _parse_date(day_word)
    )
    try:
        start_time, end_time = time(int(h1), int(m1)), time(int(h2), int(m2))
    except ValueError:
        raise PeriodError("times must be HH:MM between 00:00 and 23:59") from None
    if start_time.minute % 15 or end_time.minute % 15:
        raise PeriodError("times must be on a quarter hour (:00, :15, :30, :45)")
    start = datetime.combine(day, start_time, tzinfo=tz)
    end_day = day if end_time > start_time else day + timedelta(days=1)
    end = datetime.combine(end_day, end_time, tzinfo=tz)
    return Period(start, end, f"{day} {start_time:%H:%M}–{end_time:%H:%M}")


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise PeriodError(f"not a valid date: {text!r}") from None
