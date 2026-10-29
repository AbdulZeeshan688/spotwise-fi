"""Data-quality checks: small pure functions, no database access.

Each check looks at one Helsinki-local day and returns a CheckResult. Statuses:
pass (fine), info (worth knowing, not a problem), warn (look at it), fail (data is wrong).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any, Literal
from zoneinfo import ZoneInfo

from spotwise.ingest.sources.base import PriceSlot
from spotwise.timeutils import expected_slot_count, local_day_bounds_utc, resolution_for_day

Status = Literal["pass", "info", "warn", "fail"]

# Robust z-score above which a price counts as a spike. Spot prices are heavy-tailed,
# so the textbook 3.5 would warn almost every day; 5 only flags clear outliers.
SPIKE_THRESHOLD = 5.0
# Need at least about a day of history before the spike check means anything.
SPIKE_MIN_HISTORY = 96
# Prices normally appear around 14:00 Helsinki time; allow an hour before warning.
PUBLICATION_DEADLINE = time(15, 0)
# Keep the details JSON small.
MAX_LISTED = 10


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check for one Helsinki-local day."""

    name: str
    day: date
    status: Status
    details: dict[str, Any] = field(default_factory=dict)


def check_completeness(day: date, rows: Sequence[PriceSlot], tz: ZoneInfo) -> CheckResult:
    """DQ-01: every expected slot of the day is present (DST-aware), nothing extra."""
    resolution = resolution_for_day(day)
    start, end = local_day_bounds_utc(day, tz)
    step = timedelta(minutes=resolution)
    expected = {start + i * step for i in range(expected_slot_count(day, resolution, tz))}
    actual = {
        r.ts_start for r in rows if r.resolution_minutes == resolution and start <= r.ts_start < end
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)

    details: dict[str, Any] = {
        "resolution_minutes": resolution,
        "expected": len(expected),
        "actual": len(actual & expected),
    }
    if missing:
        details["missing"] = _times(missing, tz)
    if unexpected:
        details["unexpected"] = _times(unexpected, tz)
    return CheckResult("completeness", day, "fail" if missing or unexpected else "pass", details)


def check_duplicates(day: date, rows: Sequence[PriceSlot], tz: ZoneInfo) -> CheckResult:
    """DQ-02: no slot twice, and no hourly row for an hour that also has 15-minute rows."""
    counts = Counter((r.ts_start, r.resolution_minutes) for r in rows)
    duplicates = sorted(ts for (ts, _), n in counts.items() if n > 1)
    # Helsinki is a whole-hour offset from UTC, so truncating in UTC finds the local hour.
    hours_with_quarters = {r.ts_start.replace(minute=0) for r in rows if r.resolution_minutes == 15}
    overlaps = sorted(
        {
            r.ts_start
            for r in rows
            if r.resolution_minutes == 60 and r.ts_start in hours_with_quarters
        }
    )

    details: dict[str, Any] = {"duplicates": len(duplicates), "overlapping_hours": len(overlaps)}
    if duplicates:
        details["duplicate_slots"] = _times(duplicates, tz)
    if overlaps:
        details["overlapping_slots"] = _times(overlaps, tz)
    return CheckResult("duplicates", day, "fail" if duplicates or overlaps else "pass", details)


def check_spikes(
    day: date, rows: Sequence[PriceSlot], history: Sequence[PriceSlot], tz: ZoneInfo
) -> CheckResult:
    """DQ-03: warn about prices far outside the last 30 days, using median and MAD.

    Median/MAD is used instead of mean/std because one huge spike barely moves the
    median, while it would inflate the std and hide itself. Only ever warns.
    """
    values = [float(r.price_eur_mwh) for r in history]
    if len(values) < SPIKE_MIN_HISTORY:
        return CheckResult(
            "spikes", day, "pass", {"skipped": "not enough history", "history_slots": len(values)}
        )
    center = median(values)
    mad = median(abs(v - center) for v in values)
    if mad == 0:
        return CheckResult("spikes", day, "pass", {"skipped": "history has no spread (MAD = 0)"})

    spikes = []
    for row in rows:
        # 0.6745 scales MAD so the score is comparable to a normal z-score
        score = 0.6745 * (float(row.price_eur_mwh) - center) / mad
        if abs(score) > SPIKE_THRESHOLD:
            spikes.append(
                {
                    "time": _time(row.ts_start, tz),
                    "price_eur_mwh": float(row.price_eur_mwh),
                    "robust_z": round(score, 1),
                }
            )
    details: dict[str, Any] = {
        "history_slots": len(values),
        "median_eur_mwh": round(center, 3),
        "mad_eur_mwh": round(mad, 3),
        "threshold": SPIKE_THRESHOLD,
        "spike_count": len(spikes),
    }
    if spikes:
        details["spikes"] = spikes[:MAX_LISTED]
    return CheckResult("spikes", day, "warn" if spikes else "pass", details)


def check_negative_prices(day: date, rows: Sequence[PriceSlot], tz: ZoneInfo) -> CheckResult:
    """DQ-05: negative prices are valid data. Record them as info, never as a failure."""
    negatives = sorted((r for r in rows if r.price_eur_mwh < 0), key=lambda r: r.ts_start)
    if not negatives:
        return CheckResult("negative_prices", day, "pass", {"count": 0})
    return CheckResult(
        "negative_prices",
        day,
        "info",
        {
            "count": len(negatives),
            "min_eur_mwh": float(min(r.price_eur_mwh for r in negatives)),
            "slots": _times([r.ts_start for r in negatives], tz),
        },
    )


def check_staleness(now: datetime, tomorrow_rows: Sequence[PriceSlot], tz: ZoneInfo) -> CheckResult:
    """DQ-04: warn if tomorrow's prices are still incomplete after the publication deadline."""
    local_now = now.astimezone(tz)
    tomorrow = local_now.date() + timedelta(days=1)
    resolution = resolution_for_day(tomorrow)
    start, end = local_day_bounds_utc(tomorrow, tz)
    expected = expected_slot_count(tomorrow, resolution, tz)
    actual = len(
        {
            r.ts_start
            for r in tomorrow_rows
            if r.resolution_minutes == resolution and start <= r.ts_start < end
        }
    )
    details: dict[str, Any] = {
        "expected": expected,
        "actual": actual,
        "deadline": f"{PUBLICATION_DEADLINE:%H:%M} {tz.key}",
        "checked_at": local_now.isoformat(timespec="minutes"),
    }
    if actual >= expected:
        return CheckResult("staleness", tomorrow, "pass", {**details, "published": True})
    if local_now.time() < PUBLICATION_DEADLINE:
        return CheckResult("staleness", tomorrow, "pass", {**details, "published": False})
    return CheckResult("staleness", tomorrow, "warn", {**details, "published": False})


def worst_status(statuses: Sequence[Status]) -> Status:
    """The most severe status in a list ('info' counts like 'pass')."""
    for status in ("fail", "warn", "info"):
        if status in statuses:
            return status
    return "pass"


def _time(ts: datetime, tz: ZoneInfo) -> str:
    return ts.astimezone(tz).isoformat(timespec="minutes")


def _times(timestamps: Sequence[datetime], tz: ZoneInfo) -> list[str]:
    return [_time(ts, tz) for ts in timestamps[:MAX_LISTED]]
