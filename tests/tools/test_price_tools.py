from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from spotwise.quality.report import run_quality_checks
from spotwise.tools import price_tools as t
from spotwise.tools.price_tools import ToolContext
from tests.quality.helpers import at
from tests.tools.conftest import NOW

pytestmark = pytest.mark.db


def rng(start: str, end: str, **extra: object) -> dict[str, object]:
    return {"start": at(start), "end": at(end), **extra}


def test_resolve_period_uses_the_frozen_clock(ctx: ToolContext) -> None:
    out = t.resolve_period(ctx, t.PeriodInput(period="tomorrow"))
    assert out.start.isoformat() == "2025-11-02T00:00:00+02:00"
    assert out.timezone == "Europe/Helsinki"


def test_current_price(ctx: ToolContext) -> None:
    out = t.get_current_price(ctx, t.NoInput())
    assert out.available
    assert out.slot_start is not None and out.slot_start.isoformat() == "2025-11-01T12:00:00+02:00"
    assert out.price_c_kwh_incl_vat == Decimal("12.550")
    assert out.price_c_kwh_excl_vat == Decimal("10.000")
    assert out.vat_percent == Decimal("25.5")


def test_get_prices_hourly_and_too_many_points(ctx: ToolContext) -> None:
    hourly = t.get_prices(ctx, t.PricesInput(**rng("2025-11-01T00:00", "2025-11-02T00:00")))
    assert hourly.available and len(hourly.prices) == 24
    assert hourly.prices[2].price_c_kwh == Decimal("1.255")
    too_many = t.get_prices(
        ctx, t.PricesInput(**rng("2025-11-01T00:00", "2025-11-03T00:00", resolution=15))
    )
    assert not too_many.available and "too many" in (too_many.message or "")


def test_cheapest_and_most_expensive_window(ctx: ToolContext) -> None:
    inp = t.WindowInput(**rng("2025-11-01T00:00", "2025-11-02T00:00", duration_minutes=180))
    cheap = t.find_cheapest_window(ctx, inp)
    assert cheap.found
    assert (
        cheap.window_start is not None
        and cheap.window_start.isoformat() == "2025-11-01T02:00:00+02:00"
    )
    assert cheap.average_price_c_kwh == Decimal("1.255")
    assert cheap.coverage.complete
    dear = t.find_most_expensive_window(
        ctx, t.WindowInput(**rng("2025-11-01T00:00", "2025-11-02T00:00", duration_minutes=120))
    )
    assert (
        dear.window_start is not None
        and dear.window_start.isoformat() == "2025-11-01T17:00:00+02:00"
    )
    assert dear.average_price_c_kwh == Decimal("37.650")


def test_window_without_data_explains_publication(ctx: ToolContext) -> None:
    out = t.find_cheapest_window(
        ctx, t.WindowInput(**rng("2025-11-03T00:00", "2025-11-04T00:00", duration_minutes=60))
    )
    assert not out.found
    assert "14:00" in (out.message or "")
    assert out.coverage.available_slots == 0


def test_stats_with_negative_prices_get_no_vat(ctx: ToolContext) -> None:
    out = t.get_price_stats(ctx, t.StatsInput(**rng("2025-11-02T00:00", "2025-11-03T00:00")))
    assert out.available
    assert out.min_price_c_kwh == Decimal("-2.000")  # -20 €/MWh, no VAT on negatives
    assert out.min_at is not None and out.min_at.isoformat() == "2025-11-02T03:00:00+02:00"
    assert out.max_price_c_kwh == Decimal("6.275")
    assert out.negative_slots == 2
    assert len(out.negative_slot_starts) == 2


def test_naive_datetimes_mean_helsinki_time(ctx: ToolContext) -> None:
    inp = t.StatsInput(start="2025-11-02T03:00", end="2025-11-02T03:30")  # type: ignore[arg-type]
    out = t.get_price_stats(ctx, inp)
    assert out.start.isoformat() == "2025-11-02T03:00:00+02:00"
    assert out.max_price_c_kwh == Decimal("-2.000")


def test_compare_periods(ctx: ToolContext) -> None:
    out = t.compare_periods(
        ctx,
        t.CompareInput(
            a=t.RangeInput(**rng("2025-11-02T00:00", "2025-11-03T00:00")),
            b=t.RangeInput(**rng("2025-11-01T00:00", "2025-11-02T00:00")),
        ),
    )
    assert out.available
    assert out.period_a.mean_price_c_kwh is not None and out.period_b.mean_price_c_kwh is not None
    assert out.difference_c_kwh == out.period_b.mean_price_c_kwh - out.period_a.mean_price_c_kwh
    assert out.percent_change is not None and out.percent_change > 0


def test_estimate_cost(ctx: ToolContext) -> None:
    out = t.estimate_cost(
        ctx, t.CostInput(start=at("2025-11-01T02:00"), end=at("2025-11-01T05:00"), kwh=Decimal(40))
    )
    assert out.available
    assert out.cost_eur_excl_vat == Decimal("0.40")  # 40 kWh × 1 c/kWh
    assert out.cost_eur_incl_vat == Decimal("0.50")
    assert out.average_price_c_kwh_excl_vat == Decimal("1.000")


def test_estimate_cost_refuses_partial_data(ctx: ToolContext) -> None:
    out = t.estimate_cost(
        ctx, t.CostInput(start=at("2025-11-02T22:00"), end=at("2025-11-03T06:00"), kwh=Decimal(40))
    )
    assert not out.available
    assert out.cost_eur_incl_vat is None


def test_availability(ctx: ToolContext) -> None:
    tomorrow = t.check_data_availability(ctx, t.AvailabilityInput())
    assert tomorrow.day == date(2025, 11, 2) and tomorrow.published
    later = t.check_data_availability(ctx, t.AvailabilityInput(day=date(2025, 11, 3)))
    assert not later.published
    assert "14:00" in later.note
    assert later.latest_price_end is not None
    assert later.latest_price_end.isoformat() == "2025-11-03T00:00:00+02:00"
    assert later.earliest_price_start is not None
    assert later.earliest_price_start.isoformat() == "2025-11-01T00:00:00+02:00"
    old = t.check_data_availability(ctx, t.AvailabilityInput(day=date(2020, 1, 1)))
    assert not old.published and "No prices stored" in old.note


def test_bad_ranges_are_rejected() -> None:
    with pytest.raises(ValueError):
        t.RangeInput(**rng("2025-11-02T00:00", "2025-11-01T00:00"))
    with pytest.raises(ValueError):
        t.RangeInput(**rng("2025-01-01T00:00", "2025-12-01T00:00"))
    with pytest.raises(ValueError):
        t.WindowInput(**rng("2025-11-01T00:00", "2025-11-02T00:00", duration_minutes=5))


def test_hours_above_threshold(ctx: ToolContext) -> None:
    out = t.get_price_stats(
        ctx, t.StatsInput(**rng("2025-11-01T00:00", "2025-11-02T00:00", threshold_c_kwh="12"))
    )
    # Everything except the 3-hour cheap night is above 12 c/kWh (12.55 and 37.65)
    assert out.hours_above_threshold == Decimal("21")
    assert out.slot_minutes == 15


def test_daily_averages(ctx: ToolContext) -> None:
    out = t.get_daily_averages(ctx, t.RangeInput(**rng("2025-11-01T00:00", "2025-11-04T00:00")))
    assert out.available
    assert [d.day for d in out.days] == [date(2025, 11, 1), date(2025, 11, 2)]
    assert all(d.complete for d in out.days)
    assert out.cheapest_day is not None and out.cheapest_day.day == date(2025, 11, 2)
    assert out.most_expensive_day is not None and out.most_expensive_day.day == date(2025, 11, 1)
    assert not out.coverage.complete  # 2025-11-03 has no data


def test_data_quality_tool(ctx: ToolContext, db_session: Session) -> None:
    assert t.get_data_quality(ctx, t.NoInput()).overall == "unknown"
    run_quality_checks(db_session, "FI", ctx.tz, now=NOW, days_back=0)
    out = t.get_data_quality(ctx, t.NoInput())
    assert out.available
    assert out.overall == "green"
    assert date(2025, 11, 1) in out.days_checked
    assert all(issue.status != "pass" for issue in out.issues)
