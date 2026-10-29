"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from spotwise.db.models import IngestionRun, Price, QualityResult
from spotwise.db.session import check_db_connection, get_engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """Real database engine; skips the test when Postgres isn't running."""
    if not check_db_connection():
        pytest.skip("PostgreSQL not reachable (start it with `docker compose up -d db`)")
    yield get_engine()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session whose commits only create savepoints; everything is rolled back after
    the test, so tests never leave data behind in your local database."""
    with db_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        # Start every test from empty tables. This runs inside the transaction that is
        # rolled back below, so real data in your local database is never touched.
        for model in (Price, IngestionRun, QualityResult):
            session.execute(delete(model))
        try:
            yield session
        finally:
            session.close()
            outer.rollback()
