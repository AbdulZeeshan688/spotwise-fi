"""Hypothesis strategies for price series."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import strategies as st

from spotwise.prices.slot import PriceSlot

BASE = datetime(2025, 11, 1, tzinfo=UTC)
QUARTER = timedelta(minutes=15)

# Realistic range for Finnish spot prices in €/MWh, 3 decimals like the sources
prices = st.decimals(
    min_value=Decimal("-500"),
    max_value=Decimal("4000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def quarter_series(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 40, gaps: bool = True
) -> list[PriceSlot]:
    """Sorted 15-minute slots; with `gaps`, some slots are randomly left out."""
    values = draw(st.lists(prices, min_size=min_size, max_size=max_size))
    slots = []
    ts = BASE
    for value in values:
        if gaps and draw(st.booleans()) and draw(st.booleans()):  # ~25% chance of a gap
            ts += QUARTER
        slots.append(PriceSlot(ts, 15, value))
        ts += QUARTER
    return slots
