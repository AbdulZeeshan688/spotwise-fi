"""Read-only queries shared by the quality runner, the API and the agent tools."""

from datetime import UTC, datetime

from sqlalchemy import select
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
