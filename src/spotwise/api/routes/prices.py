"""Price endpoints (API-02, API-03). Times in responses are Helsinki time."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from spotwise.config import get_settings
from spotwise.db.queries import load_slots
from spotwise.db.session import get_session
from spotwise.prices.slot import PriceSlot
from spotwise.prices.stats import hourly_averages
from spotwise.prices.units import consumer_price_c_kwh, round_price
from spotwise.prices.windows import cheapest_window
from spotwise.timeutils import (
    expected_slot_count,
    local_day_bounds_utc,
    local_today,
    resolution_for_day,
)

router = APIRouter(prefix="/prices", tags=["prices"])

MAX_RANGE_DAYS = 92


class PricePointOut(BaseModel):
    """One price slot for display."""

    start: datetime
    end: datetime
    resolution_minutes: int
    price_c_kwh: Decimal


class PricesOut(BaseModel):
    """Prices for a time range, in c/kWh."""

    area: str
    start: datetime
    end: datetime
    timezone: str
    unit: Literal["c/kWh"] = "c/kWh"
    vat_included: bool
    vat_rate: Decimal
    resolution_minutes: int
    count: int
    prices: list[PricePointOut]


class CheapestWindowOut(BaseModel):
    """The cheapest continuous window of a given length on one day."""

    date: date
    duration_minutes: int
    start: datetime
    end: datetime
    average_price_c_kwh: Decimal
    unit: Literal["c/kWh"] = "c/kWh"
    vat_included: bool
    vat_rate: Decimal
    data_complete: bool  # False if the day has gaps: the window is from partial data


def parse_time(value: str, tz: ZoneInfo) -> datetime:
    """Accept '2026-10-29' (local midnight) or an ISO datetime (local time if no offset)."""
    try:
        if len(value) == 10:
            return local_day_bounds_utc(date.fromisoformat(value), tz)[0]
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"Not a valid date or datetime: {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


@router.get("", response_model=PricesOut)
def get_prices(
    session: Annotated[Session, Depends(get_session)],
    from_: Annotated[
        str | None,
        Query(alias="from", description="Date or ISO datetime. Default: today 00:00 Helsinki."),
    ] = None,
    to: Annotated[
        str | None,
        Query(description="Exclusive end. Default: 2 days after `from` (today + tomorrow)."),
    ] = None,
    resolution: Annotated[int, Query(description="15 = as stored, 60 = hourly averages")] = 15,
    vat: Annotated[bool, Query(description="Include VAT (default true)")] = True,
) -> PricesOut:
    """Prices in c/kWh for [from, to). Hourly-era data stays hourly at resolution=15."""
    if resolution not in (15, 60):
        raise HTTPException(422, "resolution must be 15 or 60")
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    start = parse_time(from_, tz) if from_ else local_day_bounds_utc(local_today(tz=tz), tz)[0]
    end = parse_time(to, tz) if to else start + timedelta(days=2)
    if end <= start:
        raise HTTPException(422, "`to` must be after `from`")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(422, f"Range can be at most {MAX_RANGE_DAYS} days")

    slots = load_slots(session, settings.price_area, start, end)
    if resolution == 60:
        slots = hourly_averages(slots)
    vat_rate = Decimal(str(settings.vat_rate))
    points = [_point(slot, vat, vat_rate, tz) for slot in slots]
    return PricesOut(
        area=settings.price_area,
        start=start.astimezone(tz),
        end=end.astimezone(tz),
        timezone=settings.timezone,
        vat_included=vat,
        vat_rate=vat_rate,
        resolution_minutes=resolution,
        count=len(points),
        prices=points,
    )


@router.get("/cheapest-window", response_model=CheapestWindowOut)
def get_cheapest_window(
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[
        date | None, Query(alias="date", description="Helsinki date. Default: today.")
    ] = None,
    hours: Annotated[float, Query(gt=0, le=24, description="Window length, e.g. 3 or 1.5")] = 3,
    vat: Annotated[bool, Query(description="Include VAT (default true)")] = True,
) -> CheapestWindowOut:
    """Cheapest continuous window of `hours` within one Helsinki day."""
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    today = local_today(tz=tz)
    day = day or today
    start, end = local_day_bounds_utc(day, tz)
    slots = load_slots(session, settings.price_area, start, end)
    resolution = resolution_for_day(day)
    data_complete = len(slots) >= expected_slot_count(day, resolution, tz)
    if day > today and not data_complete:
        # A few early slots can exist before publication; don't answer from those.
        raise HTTPException(
            404,
            f"Prices for {day} are not published yet. Next-day prices are published "
            "around 14:00 Finnish time.",
        )
    if not slots:
        raise HTTPException(404, f"No prices stored for {day}.")

    duration = round(hours * 60)
    try:
        window = cheapest_window(slots, duration, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if window is None:
        raise HTTPException(404, f"No continuous {hours:g} h window in the data for {day}.")

    vat_rate = Decimal(str(settings.vat_rate))
    # Average of the consumer prices, so VAT is applied per slot like everywhere else
    prices = [consumer_price_c_kwh(s.price_eur_mwh, vat, vat_rate) for s in window.slots]
    return CheapestWindowOut(
        date=day,
        duration_minutes=duration,
        start=window.start.astimezone(tz),
        end=window.end.astimezone(tz),
        average_price_c_kwh=round_price(sum(prices, Decimal(0)) / len(prices)),
        vat_included=vat,
        vat_rate=vat_rate,
        data_complete=data_complete,
    )


def _point(slot: PriceSlot, vat: bool, vat_rate: Decimal, tz: ZoneInfo) -> PricePointOut:
    return PricePointOut(
        start=slot.ts_start.astimezone(tz),
        end=slot.end.astimezone(tz),
        resolution_minutes=slot.resolution_minutes,
        price_c_kwh=round_price(consumer_price_c_kwh(slot.price_eur_mwh, vat, vat_rate)),
    )
