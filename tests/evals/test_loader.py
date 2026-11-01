import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from evals.fixtures.fixture import load_fixture
from evals.fixtures.loader import UnsafeEvalDatabaseError, check_eval_url, load_eval_database
from spotwise.db.models import Price, QualityResult

MAIN = "postgresql+psycopg://postgres:postgres@localhost:5432/spotwise"


def test_refuses_databases_that_could_be_real() -> None:
    with pytest.raises(UnsafeEvalDatabaseError, match="_eval"):
        check_eval_url("postgresql+psycopg://postgres:postgres@localhost:5432/spotwise", MAIN)
    with pytest.raises(UnsafeEvalDatabaseError):
        check_eval_url("postgresql+psycopg://u:p@h/prod", MAIN)
    check_eval_url("postgresql+psycopg://postgres:postgres@localhost:5432/spotwise_eval", MAIN)


@pytest.mark.db
def test_load_eval_database(db_engine: Engine) -> None:
    eval_url = db_engine.url.set(database="spotwise_eval").render_as_string(hide_password=False)
    engine = load_eval_database(eval_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Price)) == len(load_fixture())
        assert session.scalar(select(func.count()).select_from(QualityResult)) > 0
    # Loading twice gives the same database
    load_eval_database(eval_url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Price)) == len(load_fixture())
    engine.dispose()
