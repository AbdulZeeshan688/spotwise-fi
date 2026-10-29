"""Clean up slots from any source before they are written to the database."""

from datetime import UTC, datetime

from spotwise.ingest.sources.base import PriceSlot


def normalise_slots(slots: list[PriceSlot], start: datetime, end: datetime) -> list[PriceSlot]:
    """Return UTC slots in [start, end), one per (time, resolution), sorted by time.

    If an hour has 15-minute slots, an hourly slot for the same hour is dropped, so we
    never store two resolutions for the same time from one fetch.
    """
    unique: dict[tuple[datetime, int], PriceSlot] = {}
    for slot in slots:
        ts = slot.ts_start.astimezone(UTC)
        if start <= ts < end:
            unique[(ts, slot.resolution_minutes)] = PriceSlot(
                ts, slot.resolution_minutes, slot.price_eur_mwh
            )

    hours_with_quarters = {ts.replace(minute=0) for ts, resolution in unique if resolution == 15}
    kept = [
        slot
        for (ts, resolution), slot in unique.items()
        if not (resolution == 60 and ts in hours_with_quarters)
    ]
    return sorted(kept, key=lambda s: (s.ts_start, s.resolution_minutes))
