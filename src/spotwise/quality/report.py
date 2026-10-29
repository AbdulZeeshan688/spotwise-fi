"""Runs the quality checks against the database and saves the results (DQ-06)."""

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spotwise.db.models import QualityResult
from spotwise.db.queries import load_slots
from spotwise.prices.slot import PriceSlot
from spotwise.quality.checks import (
    CheckResult,
    Status,
    check_completeness,
    check_duplicates,
    check_negative_prices,
    check_spikes,
    check_staleness,
    worst_status,
)
from spotwise.timeutils import expected_slot_count, local_day_bounds_utc, resolution_for_day

logger = logging.getLogger(__name__)

SPIKE_HISTORY_DAYS = 30
Colour = Literal["green", "yellow", "red", "unknown"]


def run_quality_checks(
    session: Session,
    area: str,
    tz: ZoneInfo,
    now: datetime | None = None,
    days_back: int = 1,
) -> list[CheckResult]:
    """Check the last `days_back` days plus today (and tomorrow once it is published),
    save every result to `quality_results` with the same run_at, and return them."""
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date()
    tomorrow = today + timedelta(days=1)
    days = [today - timedelta(days=n) for n in range(days_back, -1, -1)]

    load_start, _ = local_day_bounds_utc(days[0] - timedelta(days=SPIKE_HISTORY_DAYS), tz)
    _, load_end = local_day_bounds_utc(tomorrow, tz)
    all_rows = load_slots(session, area, load_start, load_end)

    by_day: dict[date, list[PriceSlot]] = defaultdict(list)
    for row in all_rows:
        by_day[row.ts_start.astimezone(tz).date()].append(row)

    # Tomorrow is only checked once it's published; before that, staleness covers it.
    tomorrow_rows = by_day.get(tomorrow, [])
    tomorrow_res = resolution_for_day(tomorrow)
    published = sum(1 for r in tomorrow_rows if r.resolution_minutes == tomorrow_res)
    if published >= expected_slot_count(tomorrow, tomorrow_res, tz):
        days.append(tomorrow)

    results = []
    for day in days:
        rows = by_day.get(day, [])
        day_start, _ = local_day_bounds_utc(day, tz)
        history_start = day_start - timedelta(days=SPIKE_HISTORY_DAYS)
        history = [r for r in all_rows if history_start <= r.ts_start < day_start]
        results += [
            check_completeness(day, rows, tz),
            check_duplicates(day, rows, tz),
            check_spikes(day, rows, history, tz),
            check_negative_prices(day, rows, tz),
        ]
    results.append(check_staleness(now, tomorrow_rows, tz))

    session.add_all(
        QualityResult(run_at=now, day=r.day, check_name=r.name, status=r.status, details=r.details)
        for r in results
    )
    session.commit()

    for r in results:
        if r.status in ("warn", "fail"):
            logger.warning("Quality %s for %s: %s %s", r.name, r.day, r.status, r.details)
    logger.info(
        "Quality checks done: %d results, overall %s",
        len(results),
        overall_colour([r.status for r in results]),
    )
    return results


def overall_colour(statuses: Sequence[Status]) -> Colour:
    """Traffic light for the UI: any fail → red, any warn → yellow, else green."""
    if not statuses:
        return "unknown"
    worst = worst_status(statuses)
    return "red" if worst == "fail" else "yellow" if worst == "warn" else "green"


def load_latest_results(session: Session) -> tuple[datetime | None, list[QualityResult]]:
    """Results of the most recent quality run (all rows share its run_at)."""
    latest = session.scalar(select(func.max(QualityResult.run_at)))
    if latest is None:
        return None, []
    rows = session.scalars(
        select(QualityResult)
        .where(QualityResult.run_at == latest)
        .order_by(QualityResult.day, QualityResult.check_name)
    ).all()
    return latest, list(rows)
