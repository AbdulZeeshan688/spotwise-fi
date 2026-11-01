"""Read-only queries shared by the quality runner, the API and the agent tools."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spotwise.db.models import Price
from spotwise.prices.slot import PriceSlot


def load_slots(session: Session, area: str, start: datetime, end: datetime) -> list[PriceSlot]:
    """All stored price rows for an area with ts_start in [start, end), sorted by time."""
    rows = session.execute(
        select(Price.ts_start, Price.resolution_minutes, Price.price_eur_mwh)
        .where(Price.area == area, Price.ts_start >= start, Price.ts_start < end)
        .order_by(Price.ts_start, Price.resolution_minutes)
    ).all()
    return [PriceSlot(ts.astimezone(UTC), res, price) for ts, res, price in rows]


def price_range(session: Session, area: str) -> tuple[datetime, datetime] | None:
    """First slot start and last slot end stored for an area, or None if empty."""
    first = session.scalar(select(func.min(Price.ts_start)).where(Price.area == area))
    last = session.execute(
        select(Price.ts_start, Price.resolution_minutes)
        .where(Price.area == area)
        .order_by(Price.ts_start.desc())
        .limit(1)
    ).first()
    if first is None or last is None:
        return None
    return first.astimezone(UTC), (last[0] + timedelta(minutes=last[1])).astimezone(UTC)
