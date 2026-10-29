from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spotwise.config import Settings
from spotwise.db.models import IngestionRun, Price
from spotwise.ingest.pipeline import build_sources, day_chunks, run_ingestion, upsert_prices
from spotwise.ingest.sources.base import PriceSlot, SourceError
from spotwise.timeutils import iter_market_slots, local_day_bounds_utc

HEL = ZoneInfo("Europe/Helsinki")
AREA = "TEST"  # keeps test rows apart from real FI data


class FakeSource:
    """Returns one price per market slot, or raises if `fail` is set."""

    def __init__(self, name: str, price: str = "10", fail: bool = False) -> None:
        self.name = name
        self.price = Decimal(price)
        self.fail = fail
        self.calls = 0

    def fetch(self, start: datetime, end: datetime) -> list[PriceSlot]:
        self.calls += 1
        if self.fail:
            raise SourceError(f"{self.name}: boom")
        return [PriceSlot(ts, res, self.price) for ts, res in iter_market_slots(start, end, HEL)]


def count_prices(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Price).where(Price.area == AREA)) or 0


def test_day_chunks_cover_range_without_overlap() -> None:
    chunks = day_chunks(date(2025, 1, 1), date(2025, 3, 5), chunk_days=31)
    assert chunks[0] == (date(2025, 1, 1), date(2025, 1, 31))
    assert chunks[-1][1] == date(2025, 3, 5)
    for (_, end), (next_start, _) in zip(chunks, chunks[1:], strict=False):
        assert next_start == end + timedelta(days=1)


def test_build_sources_falls_back_to_porssisahko_without_token() -> None:
    import httpx

    with httpx.Client() as client:
        names = [s.name for s in build_sources(Settings(_env_file=None, entsoe_token=None), client)]
        assert names == ["porssisahko"]
        with_token = Settings(_env_file=None, entsoe_token="abc")  # type: ignore[arg-type]
        assert [s.name for s in build_sources(with_token, client)] == ["entsoe", "porssisahko"]


@pytest.mark.db
def test_rerun_is_idempotent(db_session: Session) -> None:
    source = FakeSource("entsoe")
    first = run_ingestion(db_session, [source], date(2024, 10, 27), date(2024, 10, 28), AREA, HEL)
    second = run_ingestion(db_session, [source], date(2024, 10, 27), date(2024, 10, 28), AREA, HEL)
    assert first.rows_upserted == 25 + 24  # hourly era; DST day has 25 hours
    assert second.rows_upserted == 0
    assert count_prices(db_session) == 49
    assert first.status == second.status == "success"


@pytest.mark.db
def test_dst_day_in_15_minute_era_has_100_slots(db_session: Session) -> None:
    run_ingestion(
        db_session, [FakeSource("entsoe")], date(2026, 10, 25), date(2026, 10, 25), AREA, HEL
    )
    start, end = local_day_bounds_utc(date(2026, 10, 25), HEL)
    n = db_session.scalar(
        select(func.count())
        .select_from(Price)
        .where(Price.area == AREA, Price.ts_start >= start, Price.ts_start < end)
    )
    assert n == 100


@pytest.mark.db
def test_changed_price_is_updated(db_session: Session) -> None:
    ts = datetime(2025, 11, 1, tzinfo=UTC)
    assert upsert_prices(db_session, [PriceSlot(ts, 15, Decimal("1"))], AREA, "entsoe") == 1
    assert upsert_prices(db_session, [PriceSlot(ts, 15, Decimal("2"))], AREA, "entsoe") == 1
    stored = db_session.scalar(select(Price.price_eur_mwh).where(Price.area == AREA))
    assert stored == Decimal("2")


@pytest.mark.db
def test_porssisahko_never_overwrites_entsoe(db_session: Session) -> None:
    ts = datetime(2025, 11, 1, tzinfo=UTC)
    upsert_prices(db_session, [PriceSlot(ts, 15, Decimal("1.234"))], AREA, "entsoe")
    written = upsert_prices(db_session, [PriceSlot(ts, 15, Decimal("1.240"))], AREA, "porssisahko")
    assert written == 0
    row = db_session.execute(
        select(Price.source, Price.price_eur_mwh).where(Price.area == AREA)
    ).one()
    assert tuple(row) == ("entsoe", Decimal("1.234"))


@pytest.mark.db
def test_fallback_source_used_when_primary_fails(db_session: Session) -> None:
    primary, fallback = FakeSource("entsoe", fail=True), FakeSource("porssisahko")
    result = run_ingestion(
        db_session, [primary, fallback], date(2025, 11, 1), date(2025, 11, 1), AREA, HEL
    )
    assert result.status == "success"
    assert result.sources_used == ["porssisahko"]
    assert result.rows_upserted == 96
    run = db_session.get(IngestionRun, result.run_id)
    assert run is not None
    assert run.source == "porssisahko"
    assert run.error is not None and "boom" in run.error


@pytest.mark.db
def test_all_sources_failing_marks_run_failed(db_session: Session) -> None:
    result = run_ingestion(
        db_session,
        [FakeSource("entsoe", fail=True)],
        date(2025, 11, 1),
        date(2025, 11, 1),
        AREA,
        HEL,
    )
    run = db_session.get(IngestionRun, result.run_id)
    assert result.status == "failed"
    assert run is not None and run.status == "failed" and run.finished_at is not None


@pytest.mark.db
def test_some_chunks_failing_marks_run_partial(db_session: Session) -> None:
    class FailsSecondCall(FakeSource):
        def fetch(self, start: datetime, end: datetime) -> list[PriceSlot]:
            self.fail = self.calls == 1
            return super().fetch(start, end)

    result = run_ingestion(
        db_session, [FailsSecondCall("entsoe")], date(2025, 1, 1), date(2025, 2, 15), AREA, HEL
    )
    assert result.status == "partial"
    assert result.rows_upserted == 31 * 24
