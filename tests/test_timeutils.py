from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from spotwise.timeutils import (
    expected_slot_count,
    iter_market_slots,
    local_day_bounds_utc,
    local_today,
    resolution_for_day,
)

HEL = ZoneInfo("Europe/Helsinki")


@pytest.mark.parametrize(
    ("day", "resolution", "expected"),
    [
        (date(2025, 3, 30), 60, 23),  # DST starts: 23-hour day
        (date(2025, 10, 26), 60, 25),  # DST ends: 25-hour day
        (date(2025, 6, 1), 60, 24),
        (date(2026, 3, 29), 15, 92),  # DST starts, 15-minute era
        (date(2026, 10, 25), 15, 100),  # DST ends, 15-minute era
        (date(2025, 11, 1), 15, 96),
    ],
)
def test_expected_slot_count_handles_dst(day: date, resolution: int, expected: int) -> None:
    assert expected_slot_count(day, resolution, HEL) == expected


def test_day_bounds_are_local_midnights_in_utc() -> None:
    start, end = local_day_bounds_utc(date(2025, 10, 26), HEL)
    assert start == datetime(2025, 10, 25, 21, tzinfo=UTC)  # 00:00 at UTC+3
    assert end == datetime(2025, 10, 26, 22, tzinfo=UTC)  # 00:00 at UTC+2


def test_resolution_switches_on_2025_10_01() -> None:
    assert resolution_for_day(date(2025, 9, 30)) == 60
    assert resolution_for_day(date(2025, 10, 1)) == 15


def test_market_slots_across_the_15_minute_switch() -> None:
    start, _ = local_day_bounds_utc(date(2025, 9, 30), HEL)
    _, end = local_day_bounds_utc(date(2025, 10, 1), HEL)
    slots = list(iter_market_slots(start, end, HEL))
    assert len(slots) == 24 + 96
    assert slots[23] == (datetime(2025, 9, 30, 20, tzinfo=UTC), 60)
    assert slots[24] == (datetime(2025, 9, 30, 21, tzinfo=UTC), 15)


def test_local_today_uses_helsinki_not_utc() -> None:
    # 22:30 UTC on 31 Oct is already 1 Nov in Helsinki (UTC+2)
    assert local_today(datetime(2025, 10, 31, 22, 30, tzinfo=UTC), HEL) == date(2025, 11, 1)
