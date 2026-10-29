from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from spotwise.ingest.normalise import normalise_slots
from spotwise.ingest.sources.base import PriceSlot

T0 = datetime(2025, 11, 1, 10, tzinfo=UTC)
FAR = datetime(2030, 1, 1, tzinfo=UTC)


def slot(ts: datetime, res: int = 15, price: str = "1") -> PriceSlot:
    return PriceSlot(ts, res, Decimal(price))


def test_hourly_slot_dropped_when_quarters_exist() -> None:
    quarters = [slot(T0 + timedelta(minutes=15 * i)) for i in range(4)]
    result = normalise_slots([slot(T0, 60), *quarters], T0, FAR)
    assert result == quarters


def test_hourly_slot_kept_when_no_quarters() -> None:
    result = normalise_slots([slot(T0, 60)], T0, FAR)
    assert result == [slot(T0, 60)]


def test_converts_to_utc_and_filters_range() -> None:
    helsinki_time = T0.astimezone(timezone(timedelta(hours=2)))
    result = normalise_slots([slot(helsinki_time), slot(T0 - timedelta(minutes=15))], T0, FAR)
    assert len(result) == 1
    assert result[0].ts_start.tzinfo == UTC


def test_duplicates_collapse_last_wins() -> None:
    result = normalise_slots([slot(T0, price="1"), slot(T0, price="2")], T0, FAR)
    assert result == [slot(T0, price="2")]
