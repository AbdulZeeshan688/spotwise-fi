"""Agent tools: typed Pydantic input/output, thin wrappers over prices/ and the DB.

Rules: no free-form SQL, all math in prices/, all VAT in prices/units.py. Prices go out
in c/kWh (3 decimals) and euros (2 decimals), times in Helsinki time. When data is
missing, a tool says so in its output instead of raising, so the agent can explain it.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from spotwise.config import Settings
from spotwise.db.queries import load_slots
from spotwise.db.session import get_engine
from spotwise.prices.slot import PriceSlot, clip, step_minutes, to_uniform_steps
from spotwise.prices.stats import estimate_cost as estimate_cost_math
from spotwise.prices.stats import hourly_averages, price_stats
from spotwise.prices.units import consumer_price_c_kwh, round_price, to_consumer_slots
from spotwise.prices.windows import cheapest_window, most_expensive_window
from spotwise.timeutils import (
    expected_slot_count,
    local_day_bounds_utc,
    local_tz,
    resolution_for_day,
)
from spotwise.tools.periods import resolve_period as resolve_period_text

MAX_RANGE_DAYS = 92
MAX_PRICE_POINTS = 100
MAX_LISTED_TIMES = 20
NOT_PUBLISHED_NOTE = "Next-day prices are published around 14:00 Finnish time."


@dataclass(frozen=True)
class ToolContext:
    """What every tool needs: DB access, area, timezone, VAT rate and a clock."""

    session_factory: Callable[[], AbstractContextManager[Session]]
    area: str
    tz: ZoneInfo
    vat_rate: Decimal
    now: Callable[[], datetime]

    @classmethod
    def from_settings(cls, settings: Settings) -> "ToolContext":
        """Real database and clock; EVAL_NOW freezes the clock for evaluations."""
        engine = get_engine()
        return cls(
            session_factory=lambda: Session(engine),
            area=settings.price_area,
            tz=ZoneInfo(settings.timezone),
            vat_rate=Decimal(str(settings.vat_rate)),
            now=lambda: settings.eval_now or datetime.now(UTC),
        )


# --- inputs -----------------------------------------------------------------


class NoInput(BaseModel):
    """Tool without arguments."""


class PeriodInput(BaseModel):
    period: str = Field(
        description="e.g. 'today', 'tomorrow', 'last week', '4 weeks ago', 'last month', "
        "'next 8 hours', '2026-10-01..2026-10-07', 'today 22:00-06:00'"
    )


def _local_if_naive(value: datetime) -> datetime:
    """A datetime without offset means Helsinki time."""
    return value if value.tzinfo else value.replace(tzinfo=local_tz())


class RangeInput(BaseModel):
    start: datetime = Field(description="Range start, ISO datetime from resolve_period")
    end: datetime = Field(description="Range end (exclusive), ISO datetime from resolve_period")
    include_vat: bool = Field(True, description="Consumer price incl. VAT (default true)")

    _start_local = field_validator("start", "end")(_local_if_naive)

    @model_validator(mode="after")
    def _check_range(self) -> "RangeInput":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > timedelta(days=MAX_RANGE_DAYS):
            raise ValueError(f"range can be at most {MAX_RANGE_DAYS} days")
        return self


class PricesInput(RangeInput):
    resolution: Literal[15, 60] = Field(60, description="60 = hourly averages, 15 = as published")


class WindowInput(RangeInput):
    duration_minutes: int = Field(
        ge=15, le=1440, description="Window length in minutes, a multiple of 15 (3 h = 180)"
    )


class CompareInput(BaseModel):
    a: RangeInput = Field(description="The reference period (e.g. last week)")
    b: RangeInput = Field(description="The period compared with it (e.g. this week)")


class CostInput(BaseModel):
    start: datetime = Field(description="Usage start, ISO datetime from resolve_period")
    end: datetime = Field(description="Usage end (exclusive)")
    kwh: Decimal = Field(gt=0, le=10000, description="Energy used, spread evenly over the range")

    _start_local = field_validator("start", "end")(_local_if_naive)

    @model_validator(mode="after")
    def _check_range(self) -> "CostInput":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > timedelta(days=MAX_RANGE_DAYS):
            raise ValueError(f"range can be at most {MAX_RANGE_DAYS} days")
        return self


class AvailabilityInput(BaseModel):
    day: date | None = Field(None, description="Helsinki date to check; default tomorrow")


# --- outputs ----------------------------------------------------------------


class Coverage(BaseModel):
    """How much of the requested range has prices."""

    expected_slots: int
    available_slots: int
    complete: bool
    slot_minutes: int


class PeriodOut(BaseModel):
    label: str
    start: datetime
    end: datetime
    timezone: str


class CurrentPriceOut(BaseModel):
    available: bool
    checked_at: datetime
    message: str | None = None
    slot_start: datetime | None = None
    slot_end: datetime | None = None
    price_c_kwh_incl_vat: Decimal | None = None
    price_c_kwh_excl_vat: Decimal | None = None
    vat_percent: Decimal


class PricePoint(BaseModel):
    start: datetime
    price_c_kwh: Decimal


class PricesOut(BaseModel):
    available: bool
    message: str | None = None
    start: datetime
    end: datetime
    unit: str = "c/kWh"
    vat_included: bool
    vat_percent: Decimal
    resolution_minutes: int
    coverage: Coverage
    prices: list[PricePoint] = []


class WindowOut(BaseModel):
    found: bool
    message: str | None = None
    kind: Literal["cheapest", "most_expensive"]
    searched_start: datetime
    searched_end: datetime
    duration_minutes: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    average_price_c_kwh: Decimal | None = None
    vat_included: bool
    vat_percent: Decimal
    coverage: Coverage


class StatsOut(BaseModel):
    available: bool
    message: str | None = None
    start: datetime
    end: datetime
    unit: str = "c/kWh"
    vat_included: bool
    vat_percent: Decimal
    min_price_c_kwh: Decimal | None = None
    min_at: datetime | None = None
    max_price_c_kwh: Decimal | None = None
    max_at: datetime | None = None
    mean_price_c_kwh: Decimal | None = None
    median_price_c_kwh: Decimal | None = None
    negative_slots: int = 0
    negative_slot_starts: list[datetime] = []
    coverage: Coverage


class PeriodMean(BaseModel):
    start: datetime
    end: datetime
    mean_price_c_kwh: Decimal | None
    coverage: Coverage


class CompareOut(BaseModel):
    available: bool
    message: str | None = None
    unit: str = "c/kWh"
    vat_included: bool
    vat_percent: Decimal
    period_a: PeriodMean
    period_b: PeriodMean
    difference_c_kwh: Decimal | None = Field(None, description="b minus a")
    percent_change: Decimal | None = None


class CostOut(BaseModel):
    available: bool
    message: str | None = None
    start: datetime
    end: datetime
    kwh: Decimal
    average_price_c_kwh_excl_vat: Decimal | None = None
    cost_eur_excl_vat: Decimal | None = None
    cost_eur_incl_vat: Decimal | None = None
    vat_percent: Decimal
    coverage: Coverage


class AvailabilityOut(BaseModel):
    day: date
    published: bool
    available_slots: int
    expected_slots: int
    checked_at: datetime
    latest_price_end: datetime | None
    note: str


# --- tools ------------------------------------------------------------------


def resolve_period(ctx: ToolContext, inp: PeriodInput) -> PeriodOut:
    """Turn a phrase like 'tomorrow' into an exact Helsinki time range."""
    period = resolve_period_text(inp.period, ctx.now(), ctx.tz)
    return PeriodOut(label=period.label, start=period.start, end=period.end, timezone=ctx.tz.key)


def get_current_price(ctx: ToolContext, inp: NoInput) -> CurrentPriceOut:
    """The price of the slot that is running right now."""
    now = ctx.now().astimezone(UTC)
    slots = _load(ctx, now - timedelta(hours=1), now + timedelta(minutes=15))
    current = [s for s in slots if s.ts_start <= now < s.end]
    vat_percent = _vat_percent(ctx)
    if not current:
        return CurrentPriceOut(
            available=False,
            checked_at=_local(ctx, now),
            message="No price stored for the current time.",
            vat_percent=vat_percent,
        )
    slot = min(current, key=lambda s: s.resolution_minutes)  # prefer a 15-min slot
    return CurrentPriceOut(
        available=True,
        checked_at=_local(ctx, now),
        slot_start=_local(ctx, slot.ts_start),
        slot_end=_local(ctx, slot.end),
        price_c_kwh_incl_vat=round_price(
            consumer_price_c_kwh(slot.price_eur_mwh, True, ctx.vat_rate)
        ),
        price_c_kwh_excl_vat=round_price(
            consumer_price_c_kwh(slot.price_eur_mwh, False, ctx.vat_rate)
        ),
        vat_percent=vat_percent,
    )


def get_prices(ctx: ToolContext, inp: PricesInput) -> PricesOut:
    """Price list for a range (hourly by default, at most 100 points)."""
    slots = _load(ctx, inp.start, inp.end)
    coverage = _coverage(slots, inp.start, inp.end)
    if inp.resolution == 60:
        slots = hourly_averages(slots)
    common = {
        "start": _local(ctx, inp.start),
        "end": _local(ctx, inp.end),
        "vat_included": inp.include_vat,
        "vat_percent": _vat_percent(ctx),
        "resolution_minutes": inp.resolution,
        "coverage": coverage,
    }
    if not slots:
        return PricesOut(available=False, message=_no_data_message(ctx, inp.end), **common)
    if len(slots) > MAX_PRICE_POINTS:
        return PricesOut(
            available=False,
            message=f"{len(slots)} points is too many; use resolution 60, a shorter range, "
            "or get_price_stats / find_cheapest_window instead.",
            **common,
        )
    prices = [
        PricePoint(
            start=_local(ctx, s.ts_start),
            price_c_kwh=round_price(
                consumer_price_c_kwh(s.price_eur_mwh, inp.include_vat, ctx.vat_rate)
            ),
        )
        for s in slots
    ]
    return PricesOut(available=True, prices=prices, **common)


def find_cheapest_window(ctx: ToolContext, inp: WindowInput) -> WindowOut:
    """Cheapest continuous block of `duration_minutes` inside the range."""
    return _window(ctx, inp, "cheapest")


def find_most_expensive_window(ctx: ToolContext, inp: WindowInput) -> WindowOut:
    """Most expensive continuous block of `duration_minutes` inside the range."""
    return _window(ctx, inp, "most_expensive")


def get_price_stats(ctx: ToolContext, inp: RangeInput) -> StatsOut:
    """Min/max (with times), mean, median and negative-price slots for a range."""
    slots = _load(ctx, inp.start, inp.end)
    common = {
        "start": _local(ctx, inp.start),
        "end": _local(ctx, inp.end),
        "vat_included": inp.include_vat,
        "vat_percent": _vat_percent(ctx),
        "coverage": _coverage(slots, inp.start, inp.end),
    }
    stats = price_stats(to_consumer_slots(slots, inp.include_vat, ctx.vat_rate))
    if stats is None:
        return StatsOut(available=False, message=_no_data_message(ctx, inp.end), **common)
    return StatsOut(
        available=True,
        min_price_c_kwh=round_price(stats.min_price_eur_mwh),
        min_at=_local(ctx, stats.min_at),
        max_price_c_kwh=round_price(stats.max_price_eur_mwh),
        max_at=_local(ctx, stats.max_at),
        mean_price_c_kwh=round_price(stats.mean_price_eur_mwh),
        median_price_c_kwh=round_price(stats.median_price_eur_mwh),
        negative_slots=stats.negative_steps,
        negative_slot_starts=[_local(ctx, ts) for ts in stats.negative_starts[:MAX_LISTED_TIMES]],
        **common,
    )


def compare_periods(ctx: ToolContext, inp: CompareInput) -> CompareOut:
    """Mean price of period b compared with period a (difference and percent)."""
    if inp.a.include_vat != inp.b.include_vat:
        raise ValueError("both periods must use the same include_vat setting")
    include_vat = inp.a.include_vat
    means = []
    for period in (inp.a, inp.b):
        slots = _load(ctx, period.start, period.end)
        stats = price_stats(to_consumer_slots(slots, include_vat, ctx.vat_rate))
        means.append(
            PeriodMean(
                start=_local(ctx, period.start),
                end=_local(ctx, period.end),
                mean_price_c_kwh=round_price(stats.mean_price_eur_mwh) if stats else None,
                coverage=_coverage(slots, period.start, period.end),
            )
        )
    a, b = means
    common = {
        "vat_included": include_vat,
        "vat_percent": _vat_percent(ctx),
        "period_a": a,
        "period_b": b,
    }
    if a.mean_price_c_kwh is None or b.mean_price_c_kwh is None:
        return CompareOut(
            available=False, message="One of the periods has no price data.", **common
        )
    # Compare the rounded means so the numbers in the answer add up exactly
    difference = b.mean_price_c_kwh - a.mean_price_c_kwh
    percent = (
        round_price(difference / abs(a.mean_price_c_kwh) * 100, 1)
        if a.mean_price_c_kwh != 0
        else None
    )
    return CompareOut(available=True, difference_c_kwh=difference, percent_change=percent, **common)


def estimate_cost(ctx: ToolContext, inp: CostInput) -> CostOut:
    """Cost of using `kwh` spread evenly over the range, excl. and incl. VAT."""
    slots = _load(ctx, inp.start, inp.end)
    common = {
        "start": _local(ctx, inp.start),
        "end": _local(ctx, inp.end),
        "kwh": inp.kwh,
        "vat_percent": _vat_percent(ctx),
        "coverage": _coverage(slots, inp.start, inp.end),
    }
    try:
        cost = estimate_cost_math(
            slots, inp.start.astimezone(UTC), inp.end.astimezone(UTC), inp.kwh, ctx.vat_rate
        )
    except ValueError:
        return CostOut(
            available=False,
            message="Prices are missing for part of this range, so no estimate. "
            + _no_data_message(ctx, inp.end),
            **common,
        )
    return CostOut(
        available=True,
        average_price_c_kwh_excl_vat=round_price(cost.mean_price_eur_mwh / 10),
        cost_eur_excl_vat=round_price(cost.cost_eur_excl_vat, 2),
        cost_eur_incl_vat=round_price(cost.cost_eur_incl_vat, 2),
        **common,
    )


def check_data_availability(ctx: ToolContext, inp: AvailabilityInput) -> AvailabilityOut:
    """Are a day's prices published yet? Default: tomorrow."""
    now = ctx.now()
    today = now.astimezone(ctx.tz).date()
    day = inp.day or today + timedelta(days=1)
    start, end = local_day_bounds_utc(day, ctx.tz)
    slots = _load(ctx, start, end)
    resolution = resolution_for_day(day)
    expected = expected_slot_count(day, resolution, ctx.tz)
    available = len({s.ts_start for s in slots if s.resolution_minutes == resolution})
    published = available >= expected
    latest = _latest_price_end(ctx)
    if published:
        note = f"All prices for {day} are available."
    elif day > today:
        note = f"Prices for {day} are not published yet. {NOT_PUBLISHED_NOTE}"
    else:
        note = f"Prices for {day} are incomplete in the database ({available}/{expected} slots)."
    return AvailabilityOut(
        day=day,
        published=published,
        available_slots=available,
        expected_slots=expected,
        checked_at=_local(ctx, now),
        latest_price_end=_local(ctx, latest) if latest else None,
        note=note,
    )


# --- helpers ----------------------------------------------------------------


def _window(
    ctx: ToolContext, inp: WindowInput, kind: Literal["cheapest", "most_expensive"]
) -> WindowOut:
    slots = _load(ctx, inp.start, inp.end)
    common = {
        "kind": kind,
        "searched_start": _local(ctx, inp.start),
        "searched_end": _local(ctx, inp.end),
        "duration_minutes": inp.duration_minutes,
        "vat_included": inp.include_vat,
        "vat_percent": _vat_percent(ctx),
        "coverage": _coverage(slots, inp.start, inp.end),
    }
    if not slots:
        return WindowOut(found=False, message=_no_data_message(ctx, inp.end), **common)
    finder = cheapest_window if kind == "cheapest" else most_expensive_window
    # Rank by what the customer pays: VAT applies only to positive prices
    window = finder(
        to_consumer_slots(slots, inp.include_vat, ctx.vat_rate),
        inp.duration_minutes,
        inp.start.astimezone(UTC),
        inp.end.astimezone(UTC),
    )
    if window is None:
        return WindowOut(
            found=False,
            message="No continuous block of that length has prices in this range.",
            **common,
        )
    return WindowOut(
        found=True,
        window_start=_local(ctx, window.start),
        window_end=_local(ctx, window.end),
        average_price_c_kwh=round_price(window.mean_price_eur_mwh),  # c/kWh after conversion
        **common,
    )


def _load(ctx: ToolContext, start: datetime, end: datetime) -> list[PriceSlot]:
    with ctx.session_factory() as session:
        return load_slots(session, ctx.area, start.astimezone(UTC), end.astimezone(UTC))


def _latest_price_end(ctx: ToolContext) -> datetime | None:
    now = ctx.now().astimezone(UTC)
    slots = _load(ctx, now - timedelta(days=3), now + timedelta(days=3))
    return max((s.end for s in slots), default=None)


def _coverage(slots: list[PriceSlot], start: datetime, end: datetime) -> Coverage:
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    step = step_minutes(slots) if slots else resolution_for_day(start.date())
    expected = int((end - start) / timedelta(minutes=step))
    available = len(clip(to_uniform_steps(slots, step), start, end))
    return Coverage(
        expected_slots=expected,
        available_slots=available,
        complete=available >= expected,
        slot_minutes=step,
    )


def _no_data_message(ctx: ToolContext, end: datetime) -> str:
    if end.astimezone(UTC) > ctx.now().astimezone(UTC) + timedelta(hours=12):
        return f"No price data for (part of) this range yet. {NOT_PUBLISHED_NOTE}"
    return "No price data stored for this range."


def _local(ctx: ToolContext, ts: datetime) -> datetime:
    return ts.astimezone(ctx.tz)


def _vat_percent(ctx: ToolContext) -> Decimal:
    return (ctx.vat_rate * 100).normalize()
