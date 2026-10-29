from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from spotwise.prices.slot import PriceSlot
from spotwise.prices.windows import cheapest_window, most_expensive_window
from tests.prices.strategies import BASE, QUARTER, quarter_series

H = timedelta(hours=1)


def quarters(*values: str, start: datetime = BASE) -> list[PriceSlot]:
    return [PriceSlot(start + i * QUARTER, 15, Decimal(v)) for i, v in enumerate(values)]


def all_windows(slots: list[PriceSlot], n: int) -> Iterator[list[PriceSlot]]:
    """Brute-force oracle: every run of n slots with no gap inside."""
    for i in range(len(slots) - n + 1):
        window = slots[i : i + n]
        if all(a.end == b.ts_start for a, b in zip(window, window[1:], strict=False)):
            yield window


def mean(window: list[PriceSlot]) -> Decimal:
    return sum((s.price_eur_mwh for s in window), Decimal(0)) / len(window)


# --- examples ---------------------------------------------------------------


def test_finds_cheapest_and_most_expensive_half_hour() -> None:
    slots = quarters("50", "40", "10", "20", "90", "80")
    cheap = cheapest_window(slots, 30)
    dear = most_expensive_window(slots, 30)
    assert cheap is not None and dear is not None
    assert (cheap.start, cheap.mean_price_eur_mwh) == (BASE + 2 * QUARTER, Decimal("15"))
    assert (dear.start, dear.mean_price_eur_mwh) == (BASE + 4 * QUARTER, Decimal("85"))
    assert cheap.end == BASE + 4 * QUARTER


def test_window_never_joins_slots_across_a_gap() -> None:
    # Cheap slots on both sides of a gap must not be combined into one window.
    slots = quarters("1", start=BASE) + quarters("1", "50", start=BASE + 2 * QUARTER)
    window = cheapest_window(slots, 30)
    assert window is not None
    assert window.start == BASE + 2 * QUARTER
    assert window.mean_price_eur_mwh == Decimal("25.5")


def test_no_window_fits_returns_none() -> None:
    assert cheapest_window(quarters("1", "2"), 60) is None
    assert cheapest_window([], 60) is None


def test_tie_returns_earliest() -> None:
    window = cheapest_window(quarters("5", "5", "5"), 15)
    assert window is not None and window.start == BASE


def test_negative_prices_make_cheapest_window() -> None:
    window = cheapest_window(quarters("10", "-5", "-8", "3"), 30)
    assert window is not None and window.mean_price_eur_mwh == Decimal("-6.5")


def test_range_limits_are_respected() -> None:
    slots = quarters("1", "1", "50", "60", "70")
    window = cheapest_window(slots, 30, start=BASE + 2 * QUARTER)
    assert window is not None and window.start == BASE + 2 * QUARTER


def test_hourly_only_data_uses_hourly_steps() -> None:
    slots = [PriceSlot(BASE + i * H, 60, Decimal(v)) for i, v in enumerate(["30", "10", "20"])]
    window = cheapest_window(slots, 120)
    assert window is not None
    assert window.step_minutes == 60
    assert (window.start, window.mean_price_eur_mwh) == (BASE + H, Decimal("15"))
    with pytest.raises(ValueError, match="multiple of 60"):
        cheapest_window(slots, 90)


def test_mixed_hourly_and_quarter_data_uses_quarter_steps() -> None:
    # Hourly slot (price 40) followed by quarters, like the 1 Oct 2025 switch.
    slots = [PriceSlot(BASE, 60, Decimal("40"))] + quarters("0", "0", start=BASE + H)
    window = cheapest_window(slots, 45)
    assert window is not None
    assert window.start == BASE + 3 * QUARTER  # last quarter of the hourly slot + 2 cheap ones
    assert window.mean_price_eur_mwh == Decimal("40") / 3


def test_bad_duration_is_rejected() -> None:
    with pytest.raises(ValueError):
        cheapest_window(quarters("1"), 0)
    with pytest.raises(ValueError, match="multiple of 15"):
        cheapest_window(quarters("1", "2"), 20)


# --- properties (PRICE-07) --------------------------------------------------


@given(quarter_series(), st.integers(min_value=1, max_value=12))
def test_cheapest_window_is_never_more_expensive_than_any_other(
    slots: list[PriceSlot], n: int
) -> None:
    window = cheapest_window(slots, n * 15)
    candidates = list(all_windows(slots, n))
    if not candidates:
        assert window is None
        return
    assert window is not None
    assert all(window.mean_price_eur_mwh <= mean(w) for w in candidates)
    assert list(window.slots) in candidates  # a real, gap-free window from the data


@given(quarter_series(), st.integers(min_value=1, max_value=12))
def test_most_expensive_window_is_never_cheaper_than_any_other(
    slots: list[PriceSlot], n: int
) -> None:
    window = most_expensive_window(slots, n * 15)
    candidates = list(all_windows(slots, n))
    assume(candidates)
    assert window is not None
    assert all(window.mean_price_eur_mwh >= mean(w) for w in candidates)


@given(quarter_series(), st.integers(min_value=1, max_value=12))
def test_cheapest_is_at_most_most_expensive(slots: list[PriceSlot], n: int) -> None:
    cheap = cheapest_window(slots, n * 15)
    dear = most_expensive_window(slots, n * 15)
    assume(cheap is not None and dear is not None)
    assert cheap is not None and dear is not None
    assert cheap.mean_price_eur_mwh <= dear.mean_price_eur_mwh
    assert cheap.end - cheap.start == timedelta(minutes=n * 15)


@given(quarter_series(gaps=False, min_size=4))
def test_window_stays_inside_the_requested_range(slots: list[PriceSlot]) -> None:
    start, end = slots[1].ts_start, slots[-1].ts_start
    window = cheapest_window(slots, 15, start, end)
    assert window is not None
    assert start <= window.start and window.end <= end
    assert window.start.tzinfo == UTC
