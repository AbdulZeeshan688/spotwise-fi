"""Database engine and session helpers."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from spotwise.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Return the shared engine for DATABASE_URL (created on first use)."""
    # pool_pre_ping drops dead connections, e.g. after Postgres restarts
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """Yield a session and close it afterwards (usable as a FastAPI dependency)."""
    factory = sessionmaker(bind=get_engine())
    with factory() as session:
        yield session


def check_db_connection() -> bool:
    """Return True if the database answers `SELECT 1`."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # any driver/network error means "not reachable"
        return False
