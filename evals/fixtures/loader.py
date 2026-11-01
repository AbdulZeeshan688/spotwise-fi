"""Create the separate eval database and fill it with the frozen fixture.

    uv run python -m evals.fixtures.loader

Safe by design: it only ever touches a database whose name ends in `_eval` and that is
not DATABASE_URL, so it can never wipe your real data.
"""

import logging
from datetime import UTC

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from evals.fixtures.fixture import EVAL_NOW, FIRST_DAY, LAST_DAY, load_fixture
from spotwise.config import get_settings
from spotwise.db.models import IngestionRun, Price, QualityResult
from spotwise.ingest.pipeline import upsert_prices
from spotwise.quality.report import run_quality_checks
from spotwise.timeutils import local_tz

logger = logging.getLogger(__name__)


class UnsafeEvalDatabaseError(RuntimeError):
    """EVAL_DATABASE_URL points at a database we must not wipe."""


def check_eval_url(eval_url: str, main_url: str) -> None:
    """Refuse anything that could be the real database."""
    name = make_url(eval_url).database or ""
    if not name.endswith("_eval"):
        raise UnsafeEvalDatabaseError(f"eval database name must end in '_eval', got {name!r}")
    if make_url(eval_url) == make_url(main_url):
        raise UnsafeEvalDatabaseError("EVAL_DATABASE_URL must differ from DATABASE_URL")


def ensure_database_exists(eval_url: str) -> None:
    """CREATE DATABASE on the same server if it doesn't exist yet."""
    url = make_url(eval_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            logger.info("Created database %s", url.database)
    admin.dispose()


def load_eval_database(eval_url: str | None = None) -> Engine:
    """Migrate the eval DB, replace its contents with the fixture, run quality checks."""
    settings = get_settings()
    eval_url = eval_url or settings.eval_database_url
    check_eval_url(eval_url, settings.database_url)
    ensure_database_exists(eval_url)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes["database_url"] = eval_url
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(eval_url)
    rows = load_fixture()
    with Session(engine) as session:
        # Only the eval database: start from exactly the fixture, nothing else
        for model in (Price, IngestionRun, QualityResult):
            session.execute(delete(model))
        for source in sorted({r.source for r in rows}):
            upsert_prices(
                session, [r.slot for r in rows if r.source == source], settings.price_area, source
            )
        session.commit()
        stored = session.scalar(select(func.count()).select_from(Price))
        days = (LAST_DAY - FIRST_DAY).days
        run_quality_checks(
            session, settings.price_area, local_tz(), now=EVAL_NOW.astimezone(UTC), days_back=days
        )
    logger.info("Eval database ready: %d price rows, %s..%s", stored, FIRST_DAY, LAST_DAY)
    return engine


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_eval_database()
