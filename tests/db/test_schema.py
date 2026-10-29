from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from spotwise.db.models import Base


def test_models_define_the_three_tables() -> None:
    assert set(Base.metadata.tables) == {"prices", "ingestion_runs", "quality_results"}


def test_prices_unique_key_is_area_ts_resolution() -> None:
    prices = Base.metadata.tables["prices"]
    unique_cols = [
        [col.name for col in c.columns]
        for c in prices.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert ["area", "ts_start", "resolution_minutes"] in unique_cols


@pytest.mark.db
def test_migrated_database_has_tables_and_view(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    assert {"prices", "ingestion_runs", "quality_results"} <= set(inspector.get_table_names())
    assert "prices_hourly" in inspector.get_view_names()


@pytest.mark.db
def test_duplicate_slot_is_rejected(db_engine: Engine) -> None:
    ts = datetime(2025, 1, 1, tzinfo=UTC)
    insert = text(
        "INSERT INTO prices (ts_start, resolution_minutes, price_eur_mwh, source) "
        "VALUES (:ts, 60, 10.0, 'test')"
    )
    # Run inside a transaction we roll back, so the test leaves no data behind.
    with db_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(insert, {"ts": ts})
            with pytest.raises(IntegrityError):
                conn.execute(insert, {"ts": ts})
        finally:
            trans.rollback()


@pytest.mark.db
def test_hourly_view_averages_quarters(db_engine: Engine) -> None:
    rows = [
        (datetime(2025, 11, 1, 10, m, tzinfo=UTC), p)
        for m, p in [(0, 4), (15, 8), (30, 12), (45, 16)]
    ]
    with db_engine.connect() as conn:
        trans = conn.begin()
        try:
            for ts, price in rows:
                conn.execute(
                    text(
                        "INSERT INTO prices (ts_start, resolution_minutes, price_eur_mwh, source) "
                        "VALUES (:ts, 15, :p, 'test')"
                    ),
                    {"ts": ts, "p": price},
                )
            # An hourly row for the same hour must be ignored in favour of the quarters
            conn.execute(
                text(
                    "INSERT INTO prices (ts_start, resolution_minutes, price_eur_mwh, source) "
                    "VALUES (:ts, 60, 999, 'test')"
                ),
                {"ts": rows[0][0]},
            )
            avg = conn.execute(
                text("SELECT price_eur_mwh FROM prices_hourly WHERE ts_start = :ts"),
                {"ts": rows[0][0]},
            ).scalar_one()
        finally:
            trans.rollback()
    assert float(avg) == 10.0
