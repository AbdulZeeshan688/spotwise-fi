from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from spotwise.db.models import QualityResult
from spotwise.ingest.pipeline import upsert_prices
from spotwise.quality.report import load_latest_results, overall_colour, run_quality_checks
from tests.quality.helpers import HEL, at, day_rows

AREA = "TEST"
TODAY = date(2025, 11, 1)


def test_overall_colour() -> None:
    assert overall_colour([]) == "unknown"
    assert overall_colour(["pass", "info"]) == "green"
    assert overall_colour(["pass", "warn"]) == "yellow"
    assert overall_colour(["warn", "fail"]) == "red"


@pytest.mark.db
def test_run_saves_results_with_one_run_at(db_session: Session) -> None:
    for day in (TODAY - timedelta(days=1), TODAY):
        upsert_prices(db_session, day_rows(day), AREA, "entsoe")
    now = at("2025-11-01T12:00")

    results = run_quality_checks(db_session, AREA, HEL, now=now)

    # 2 days x 4 checks + staleness (tomorrow not published, before deadline)
    assert len(results) == 9
    assert {r.status for r in results} <= {"pass", "info"}
    run_at, saved = load_latest_results(db_session)
    assert run_at == now
    assert len(saved) == 9


@pytest.mark.db
def test_deleted_row_makes_completeness_fail(db_session: Session) -> None:
    rows = day_rows(TODAY)
    upsert_prices(db_session, rows[:40] + rows[41:], AREA, "entsoe")  # 10:00 missing

    results = run_quality_checks(db_session, AREA, HEL, now=at("2025-11-01T12:00"), days_back=0)

    completeness = next(r for r in results if r.name == "completeness")
    assert completeness.status == "fail"
    assert completeness.details["missing"] == ["2025-11-01T10:00+02:00"]


@pytest.mark.db
def test_tomorrow_checked_only_once_published(db_session: Session) -> None:
    tomorrow = TODAY + timedelta(days=1)
    upsert_prices(db_session, day_rows(TODAY), AREA, "entsoe")
    upsert_prices(db_session, day_rows(tomorrow)[:4], AREA, "porssisahko")  # only a few slots

    early = run_quality_checks(db_session, AREA, HEL, now=at("2025-11-01T12:00"), days_back=0)
    assert {r.day for r in early if r.name == "completeness"} == {TODAY}

    upsert_prices(db_session, day_rows(tomorrow), AREA, "entsoe")
    later = run_quality_checks(db_session, AREA, HEL, now=at("2025-11-01T15:30"), days_back=0)
    assert {r.day for r in later if r.name == "completeness"} == {TODAY, tomorrow}
    assert next(r for r in later if r.name == "staleness").status == "pass"


@pytest.mark.db
def test_missing_tomorrow_after_deadline_is_yellow(db_session: Session) -> None:
    upsert_prices(db_session, day_rows(TODAY), AREA, "entsoe")
    results = run_quality_checks(db_session, AREA, HEL, now=at("2025-11-01T16:00"), days_back=0)
    assert overall_colour([r.status for r in results]) == "yellow"
    saved = db_session.scalars(
        select(QualityResult).where(QualityResult.check_name == "staleness")
    ).all()
    assert [r.status for r in saved] == ["warn"]
