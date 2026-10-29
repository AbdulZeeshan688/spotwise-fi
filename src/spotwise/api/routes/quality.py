"""Data-quality summary endpoint (API-04)."""

from datetime import date, datetime
from typing import Annotated, Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from spotwise.config import get_settings
from spotwise.db.session import get_session
from spotwise.quality.checks import Status, worst_status
from spotwise.quality.report import Colour, load_latest_results, overall_colour

router = APIRouter(tags=["quality"])


class QualityCheckOut(BaseModel):
    """One check result for one Helsinki-local day."""

    check_name: str
    day: date
    status: Status
    details: dict[str, Any]


class QualitySummaryOut(BaseModel):
    """Latest quality run: overall colour, worst status per check, and every result."""

    overall: Colour
    run_at: datetime | None  # Helsinki time
    checks: dict[str, Status]
    results: list[QualityCheckOut]


@router.get("/quality/latest", response_model=QualitySummaryOut)
def quality_latest(session: Annotated[Session, Depends(get_session)]) -> QualitySummaryOut:
    """Summary of the most recent data-quality run."""
    run_at, rows = load_latest_results(session)
    results = [
        QualityCheckOut(
            check_name=r.check_name, day=r.day, status=cast(Status, r.status), details=r.details
        )
        for r in rows
    ]
    by_check: dict[str, list[Status]] = {}
    for result in results:
        by_check.setdefault(result.check_name, []).append(result.status)

    tz = ZoneInfo(get_settings().timezone)
    return QualitySummaryOut(
        overall=overall_colour([r.status for r in results]),
        run_at=run_at.astimezone(tz) if run_at else None,
        checks={name: worst_status(statuses) for name, statuses in sorted(by_check.items())},
        results=results,
    )
