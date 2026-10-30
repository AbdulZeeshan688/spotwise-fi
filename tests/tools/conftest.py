"""A ToolContext over the test database with a frozen clock and known prices."""

from contextlib import nullcontext
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from spotwise.ingest.pipeline import upsert_prices
from spotwise.tools.price_tools import ToolContext
from tests.quality.helpers import HEL, at, day_rows

TODAY = date(2025, 11, 1)
TOMORROW = date(2025, 11, 2)
NOW = at("2025-11-01T12:05")


def today_price(i: int) -> str:
    """Cheap night 02:00-05:00 (10 €/MWh), expensive 17:00-19:00 (300), else 100."""
    if 8 <= i < 20:
        return "10"
    if 68 <= i < 76:
        return "300"
    return "100"


def tomorrow_price(i: int) -> str:
    """Two negative quarters at 03:00 (-20 €/MWh), else 50."""
    return "-20" if i in (12, 13) else "50"


@pytest.fixture
def ctx(db_session: Session) -> ToolContext:
    upsert_prices(db_session, day_rows(TODAY, today_price), "FI", "entsoe")
    upsert_prices(db_session, day_rows(TOMORROW, tomorrow_price), "FI", "entsoe")
    return ToolContext(
        session_factory=lambda: nullcontext(db_session),
        area="FI",
        tz=HEL,
        vat_rate=Decimal("0.255"),
        now=lambda: NOW,
    )
