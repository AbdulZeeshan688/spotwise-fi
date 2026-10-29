"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from spotwise.db.session import check_db_connection, get_engine


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """Real database engine; skips the test when Postgres isn't running."""
    if not check_db_connection():
        pytest.skip("PostgreSQL not reachable (start it with `docker compose up -d db`)")
    yield get_engine()
