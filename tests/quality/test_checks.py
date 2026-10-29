from datetime import date, timedelta
from decimal import Decimal

import pytest

from spotwise.prices.slot import PriceSlot
from spotwise.quality.checks import (
    check_completeness,
    check_duplicates,
    check_negative_prices,
    check_spikes,
    check_staleness,
    worst_status,
)
from tests.quality.helpers import HEL, at, day_rows

QUARTER_DAY = date(2025, 11, 1)


# --- completeness (DQ-01) ---------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 11, 1), 96),
        (date(2026, 3, 29), 92),  # DST starts, 23-hour day
        (date(2026, 10, 25), 100),  # DST ends, 25-hour day
        (date(2024, 3, 31), 23),  # hourly era, DST starts
        (date(2024, 10, 27), 25),  # hourly era, DST ends
    ],
)
def test_complete_day_passes_including_dst(day: date, expected: int) -> None:
    result = check_completeness(day, day_rows(day), HEL)
    assert result.status == "pass"
    assert result.details["expected"] == result.details["actual"] == expected


def test_day_with_a_gap_fails_and_lists_missing_slot() -> None:
    rows = day_rows(QUARTER_DAY)
    del rows[40]  # 10:00 Helsinki
    result = check_completeness(QUARTER_DAY, rows, HEL)
    assert result.status == "fail"
    assert result.details["actual"] == 95
    assert result.details["missing"] == ["2025-11-01T10:00+02:00"]


def test_empty_day_fails() -> None:
    result = check_completeness(QUARTER_DAY, [], HEL)
    assert result.status == "fail"
    assert result.details["actual"] == 0


def test_misaligned_slot_is_reported_as_unexpected() -> None:
    rows = day_rows(QUARTER_DAY)
    rows.append(PriceSlot(rows[0].ts_start + timedelta(minutes=5), 15, Decimal("1")))
    result = check_completeness(QUARTER_DAY, rows, HEL)
    assert result.status == "fail"
    assert result.details["unexpected"] == ["2025-11-01T00:05+02:00"]


# --- duplicates (DQ-02) -----------------------------------------------------


def test_clean_day_has_no_duplicates() -> None:
    assert check_duplicates(QUARTER_DAY, day_rows(QUARTER_DAY), HEL).status == "pass"


def test_duplicate_slot_fails() -> None:
    rows = day_rows(QUARTER_DAY)
    rows.append(rows[3])
    result = check_duplicates(QUARTER_DAY, rows, HEL)
    assert result.status == "fail"
    assert result.details["duplicate_slots"] == ["2025-11-01T00:45+02:00"]


def test_hourly_row_overlapping_quarters_fails() -> None:
    rows = day_rows(QUARTER_DAY)
    rows.append(PriceSlot(rows[4].ts_start, 60, Decimal("50")))  # 01:00 as an hourly row
    result = check_duplicates(QUARTER_DAY, rows, HEL)
    assert result.status == "fail"
    assert result.details["overlapping_slots"] == ["2025-11-01T01:00+02:00"]


# --- spikes (DQ-03) ---------------------------------------------------------


def history_rows() -> list[PriceSlot]:
    """30 days of prices cycling 40..59 €/MWh, so median ≈ 50 and MAD ≈ 5."""
    rows: list[PriceSlot] = []
    for n in range(30):
        rows += day_rows(QUARTER_DAY - timedelta(days=30 - n), lambda i: str(40 + i % 20))
    return rows


def test_normal_day_has_no_spikes() -> None:
    result = check_spikes(QUARTER_DAY, day_rows(QUARTER_DAY, lambda i: "55"), history_rows(), HEL)
    assert result.status == "pass"
    assert result.details["spike_count"] == 0


def test_spike_warns_never_fails() -> None:
    rows = day_rows(QUARTER_DAY)
    rows[72] = PriceSlot(rows[72].ts_start, 15, Decimal("900"))  # 18:00
    result = check_spikes(QUARTER_DAY, rows, history_rows(), HEL)
    assert result.status == "warn"
    assert result.details["spike_count"] == 1
    assert result.details["spikes"][0]["time"] == "2025-11-01T18:00+02:00"
    assert result.details["spikes"][0]["price_eur_mwh"] == 900.0


def test_one_huge_spike_in_history_does_not_hide_the_next_one() -> None:
    # With mean/std, a 5000 €/MWh slot in history would inflate the std a lot.
    # Median/MAD barely move, so a 900 €/MWh price is still flagged.
    history = history_rows()
    history[100] = PriceSlot(history[100].ts_start, 15, Decimal("5000"))
    rows = day_rows(QUARTER_DAY)
    rows[0] = PriceSlot(rows[0].ts_start, 15, Decimal("900"))
    assert check_spikes(QUARTER_DAY, rows, history, HEL).status == "warn"


def test_spike_check_skips_without_enough_history() -> None:
    result = check_spikes(QUARTER_DAY, day_rows(QUARTER_DAY), [], HEL)
    assert result.status == "pass"
    assert result.details["skipped"] == "not enough history"


def test_spike_check_skips_flat_history() -> None:
    flat = day_rows(QUARTER_DAY - timedelta(days=1))  # all 50 → MAD 0
    assert "skipped" in check_spikes(QUARTER_DAY, day_rows(QUARTER_DAY), flat, HEL).details


# --- negative prices (DQ-05) ------------------------------------------------


def test_negative_prices_are_info_not_failure() -> None:
    rows = day_rows(QUARTER_DAY, lambda i: "-2.5" if i in (8, 9) else "10")
    result = check_negative_prices(QUARTER_DAY, rows, HEL)
    assert result.status == "info"
    assert result.details["count"] == 2
    assert result.details["min_eur_mwh"] == -2.5
    assert result.details["slots"] == ["2025-11-01T02:00+02:00", "2025-11-01T02:15+02:00"]


def test_no_negative_prices_passes() -> None:
    assert check_negative_prices(QUARTER_DAY, day_rows(QUARTER_DAY), HEL).status == "pass"


# --- staleness (DQ-04) ------------------------------------------------------


def test_tomorrow_missing_before_deadline_is_fine() -> None:
    result = check_staleness(at("2025-10-31T13:00"), [], HEL)
    assert result.status == "pass"
    assert result.day == QUARTER_DAY
    assert result.details["published"] is False


def test_tomorrow_missing_after_deadline_warns() -> None:
    result = check_staleness(at("2025-10-31T16:00"), [], HEL)
    assert result.status == "warn"


def test_tomorrow_partly_published_after_deadline_warns() -> None:
    result = check_staleness(at("2025-10-31T16:00"), day_rows(QUARTER_DAY)[:4], HEL)
    assert result.status == "warn"
    assert result.details["actual"] == 4


def test_tomorrow_published_passes_even_for_dst_day() -> None:
    dst_day = date(2026, 3, 29)
    result = check_staleness(at("2026-03-28T16:00"), day_rows(dst_day), HEL)
    assert result.status == "pass"
    assert result.details["expected"] == 92


# --- helpers ----------------------------------------------------------------


def test_worst_status() -> None:
    assert worst_status(["pass", "info", "warn"]) == "warn"
    assert worst_status(["pass", "fail", "warn"]) == "fail"
    assert worst_status(["pass", "info"]) == "info"
    assert worst_status([]) == "pass"
