from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from spotwise.prices.slot import PriceSlot
from spotwise.prices.stats import compare_periods, estimate_cost, hourly_averages, price_stats
from tests.prices.strategies import BASE, QUARTER, prices, quarter_series

VAT = Decimal("0.255")
H = timedelta(hours=1)


def quarters(*values: str) -> list[PriceSlot]:
    return [PriceSlot(BASE + i * QUARTER, 15, Decimal(v)) for i, v in enumerate(values)]


# --- price_stats (PRICE-04) -------------------------------------------------


def test_stats_with_times_and_negatives() -> None:
    stats = price_stats(quarters("10", "-4", "30", "-4", "50"))
    assert stats is not None
    assert (stats.min_price_eur_mwh, stats.min_at) == (Decimal("-4"), BASE + QUARTER)  # earliest
    assert (stats.max_price_eur_mwh, stats.max_at) == (Decimal("50"), BASE + 4 * QUARTER)
    assert stats.mean_price_eur_mwh == Decimal("16.4")
    assert stats.median_price_eur_mwh == Decimal("10")
    assert stats.negative_steps == 2
    assert stats.negative_starts == (BASE + QUARTER, BASE + 3 * QUARTER)
    assert (stats.start, stats.end) == (BASE, BASE + 5 * QUARTER)


def test_stats_of_nothing_is_none() -> None:
    assert price_stats([]) is None


def test_mixed_resolution_mean_is_time_weighted() -> None:
    # One hour at 40 and one quarter at 0: the hour counts four times as much.
    slots = [PriceSlot(BASE, 60, Decimal("40")), PriceSlot(BASE + H, 15, Decimal("0"))]
    stats = price_stats(slots)
    assert stats is not None and stats.mean_price_eur_mwh == Decimal("32")


@given(quarter_series())
def test_min_le_median_and_mean_le_max(slots: list[PriceSlot]) -> None:
    stats = price_stats(slots)
    assert stats is not None
    assert stats.min_price_eur_mwh <= stats.median_price_eur_mwh <= stats.max_price_eur_mwh
    assert stats.min_price_eur_mwh <= stats.mean_price_eur_mwh <= stats.max_price_eur_mwh


# --- compare_periods (PRICE-05) ---------------------------------------------


def test_compare_periods() -> None:
    result = compare_periods(quarters("40", "60"), quarters("60", "60"))
    assert result.difference_eur_mwh == Decimal("10")
    assert result.percent_change == Decimal("20")


def test_compare_with_zero_mean_has_no_percent() -> None:
    assert compare_periods(quarters("0"), quarters("5")).percent_change is None


def test_compare_needs_data() -> None:
    with pytest.raises(ValueError):
        compare_periods([], quarters("1"))


@given(quarter_series(), quarter_series())
def test_difference_is_b_minus_a(a: list[PriceSlot], b: list[PriceSlot]) -> None:
    result = compare_periods(a, b)
    assert result.difference_eur_mwh == result.mean_b_eur_mwh - result.mean_a_eur_mwh


# --- estimate_cost (PRICE-06) -----------------------------------------------


def test_cost_example_40_kwh() -> None:
    # 40 kWh over one hour at 100 €/MWh = 40 × 0.10 € = 4 € excl. VAT, 5.02 € incl.
    slots = quarters("100", "100", "100", "100")
    cost = estimate_cost(slots, BASE, BASE + H, Decimal("40"), VAT)
    assert cost.cost_eur_excl_vat == Decimal("4")
    assert cost.cost_eur_incl_vat == Decimal("5.02")


def test_cost_no_vat_on_negative_slots() -> None:
    slots = quarters("100", "-100")  # 1 kWh per slot
    cost = estimate_cost(slots, BASE, BASE + 2 * QUARTER, Decimal("2"), VAT)
    assert cost.cost_eur_excl_vat == Decimal("0")
    assert cost.cost_eur_incl_vat == Decimal("0.0255")  # only the positive slot gets VAT


def test_cost_fails_when_prices_are_missing() -> None:
    slots = quarters("1", "1") + [PriceSlot(BASE + 3 * QUARTER, 15, Decimal("1"))]
    with pytest.raises(ValueError, match="missing"):
        estimate_cost(slots, BASE, BASE + 4 * QUARTER, Decimal("1"), VAT)
    with pytest.raises(ValueError, match="missing"):
        estimate_cost(quarters("1"), BASE, BASE + H, Decimal("1"), VAT)


@given(quarter_series(gaps=False), st.decimals(min_value=0, max_value=1000, places=2))
def test_even_spread_costs_mean_price_times_kwh(slots: list[PriceSlot], kwh: Decimal) -> None:
    cost = estimate_cost(slots, slots[0].ts_start, slots[-1].end, kwh, VAT)
    expected = cost.mean_price_eur_mwh * kwh / 1000
    assert abs(cost.cost_eur_excl_vat - expected) < Decimal("1e-15")


@given(st.lists(prices.filter(lambda p: p > 0), min_size=1, max_size=20))
def test_positive_prices_cost_exactly_vat_more(values: list[Decimal]) -> None:
    slots = [PriceSlot(BASE + i * QUARTER, 15, v) for i, v in enumerate(values)]
    cost = estimate_cost(slots, BASE, slots[-1].end, Decimal("10"), VAT)
    assert abs(cost.cost_eur_incl_vat - cost.cost_eur_excl_vat * (1 + VAT)) < Decimal("1e-15")


# --- hourly_averages --------------------------------------------------------


def test_hourly_average_of_quarters() -> None:
    hours = hourly_averages(quarters("4", "8", "12", "16", "100"))
    assert hours == [
        PriceSlot(BASE, 60, Decimal("10")),
        PriceSlot(BASE + H, 60, Decimal("100")),
    ]


def test_hourly_slot_stays_the_same() -> None:
    assert hourly_averages([PriceSlot(BASE, 60, Decimal("7"))]) == [
        PriceSlot(BASE, 60, Decimal("7"))
    ]
