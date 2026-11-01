"""Statistics, period comparison, cost estimates and hourly averages (PRICE-04..06)."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

from spotwise.prices.slot import PriceSlot, clip, contiguous_runs, step_minutes, to_uniform_steps
from spotwise.prices.units import apply_vat


@dataclass(frozen=True)
class PriceStats:
    """Summary of a price series (€/MWh excl. VAT).

    Mixed hourly/15-minute data is split into equal steps first, so the mean and
    median are time-weighted. `negative_steps` counts steps of `step_minutes`.
    """

    start: datetime
    end: datetime
    step_minutes: int
    step_count: int
    min_price_eur_mwh: Decimal
    min_at: datetime
    max_price_eur_mwh: Decimal
    max_at: datetime
    mean_price_eur_mwh: Decimal
    median_price_eur_mwh: Decimal
    negative_steps: int
    negative_starts: tuple[datetime, ...]


@dataclass(frozen=True)
class PeriodComparison:
    """Mean of period B compared with period A (B − A)."""

    mean_a_eur_mwh: Decimal
    mean_b_eur_mwh: Decimal
    difference_eur_mwh: Decimal
    percent_change: Decimal | None  # None when period A's mean is exactly 0


@dataclass(frozen=True)
class CostEstimate:
    """Cost of using `kwh` spread evenly over [start, end)."""

    kwh: Decimal
    start: datetime
    end: datetime
    mean_price_eur_mwh: Decimal
    cost_eur_excl_vat: Decimal
    cost_eur_incl_vat: Decimal
    vat_rate: Decimal


def price_stats(slots: Sequence[PriceSlot]) -> PriceStats | None:
    """Min, max (with times), mean, median and negative steps. None for no data."""
    if not slots:
        return None
    step = step_minutes(slots)
    steps = to_uniform_steps(slots, step)
    prices = [s.price_eur_mwh for s in steps]
    # min()/max() return the first match, so ties resolve to the earliest time
    lowest = min(steps, key=lambda s: s.price_eur_mwh)
    highest = max(steps, key=lambda s: s.price_eur_mwh)
    negatives = tuple(s.ts_start for s in steps if s.price_eur_mwh < 0)
    return PriceStats(
        start=steps[0].ts_start,
        end=steps[-1].end,
        step_minutes=step,
        step_count=len(steps),
        min_price_eur_mwh=lowest.price_eur_mwh,
        min_at=lowest.ts_start,
        max_price_eur_mwh=highest.price_eur_mwh,
        max_at=highest.ts_start,
        mean_price_eur_mwh=sum(prices, Decimal(0)) / len(prices),
        median_price_eur_mwh=Decimal(median(prices)),
        negative_steps=len(negatives),
        negative_starts=negatives,
    )


def compare_periods(a: Sequence[PriceSlot], b: Sequence[PriceSlot]) -> PeriodComparison:
    """Compare the mean price of period B with period A, in €/MWh and percent."""
    stats_a, stats_b = price_stats(a), price_stats(b)
    if stats_a is None or stats_b is None:
        raise ValueError("both periods need price data")
    mean_a, mean_b = stats_a.mean_price_eur_mwh, stats_b.mean_price_eur_mwh
    difference = mean_b - mean_a
    percent = difference / abs(mean_a) * 100 if mean_a != 0 else None
    return PeriodComparison(mean_a, mean_b, difference, percent)


def estimate_cost(
    slots: Sequence[PriceSlot],
    start: datetime,
    end: datetime,
    kwh: Decimal,
    vat_rate: Decimal,
) -> CostEstimate:
    """Total € for `kwh` used evenly over [start, end). Fails if any part has no price.

    VAT is added per step, and only to positive prices (see units.apply_vat), so with
    negative prices "incl. VAT" is not simply "excl. VAT × 1.255".
    """
    if kwh < 0:
        raise ValueError("kWh cannot be negative")
    step = step_minutes(slots)
    steps = clip(to_uniform_steps(slots, step), start, end)
    runs = contiguous_runs(steps)
    if len(runs) != 1 or runs[0][0].ts_start != start or runs[0][-1].end != end:
        raise ValueError("prices are missing for part of the requested time range")

    kwh_per_step = kwh / len(steps)
    # €/MWh → €/kWh is ÷ 1000
    excl = sum((s.price_eur_mwh / 1000 * kwh_per_step for s in steps), Decimal(0))
    incl = sum(
        (apply_vat(s.price_eur_mwh, vat_rate) / 1000 * kwh_per_step for s in steps), Decimal(0)
    )
    mean = sum((s.price_eur_mwh for s in steps), Decimal(0)) / len(steps)
    return CostEstimate(kwh, start, end, mean, excl, incl, vat_rate)


def hourly_averages(slots: Sequence[PriceSlot]) -> list[PriceSlot]:
    """One 60-minute slot per hour: the mean of that hour's quarters (or the hourly price).

    An hour with missing quarters is averaged over the quarters that exist; the
    completeness check is where gaps are reported.
    """
    by_hour: dict[datetime, list[Decimal]] = defaultdict(list)
    for step in to_uniform_steps(slots, 15) if slots else []:
        # Helsinki is a whole-hour offset from UTC, so UTC hours are local hours.
        by_hour[step.ts_start.replace(minute=0)].append(step.price_eur_mwh)
    return [
        PriceSlot(hour, 60, sum(prices, Decimal(0)) / len(prices))
        for hour, prices in sorted(by_hour.items())
    ]


@dataclass(frozen=True)
class DailyMean:
    """Mean price of one local day and how many steps it is based on."""

    day: date
    mean_price_eur_mwh: Decimal
    step_minutes: int
    step_count: int


def daily_means(slots: Sequence[PriceSlot], tz: ZoneInfo) -> list[DailyMean]:
    """Time-weighted mean per local day (the timezone decides where a day starts)."""
    if not slots:
        return []
    step = step_minutes(slots)
    by_day: dict[date, list[Decimal]] = defaultdict(list)
    for s in to_uniform_steps(slots, step):
        by_day[s.ts_start.astimezone(tz).date()].append(s.price_eur_mwh)
    return [
        DailyMean(day, sum(prices, Decimal(0)) / len(prices), step, len(prices))
        for day, prices in sorted(by_day.items())
    ]


def minutes_above(slots: Sequence[PriceSlot], threshold: Decimal) -> int:
    """Total minutes with a price strictly above `threshold` (same unit as the slots)."""
    return sum(s.resolution_minutes for s in slots if s.price_eur_mwh > threshold)
