"""Cheapest / most expensive contiguous time window (PRICE-02, PRICE-03)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from spotwise.prices.slot import PriceSlot, clip, contiguous_runs, step_minutes, to_uniform_steps


@dataclass(frozen=True)
class PriceWindow:
    """A block of consecutive slots and its average price (€/MWh excl. VAT)."""

    start: datetime
    end: datetime
    mean_price_eur_mwh: Decimal
    step_minutes: int
    slots: tuple[PriceSlot, ...]


def cheapest_window(
    slots: Sequence[PriceSlot],
    duration_minutes: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> PriceWindow | None:
    """Lowest-average window of `duration_minutes` inside [start, end), or None if none fits."""
    return _best_window(slots, duration_minutes, start, end, "min")


def most_expensive_window(
    slots: Sequence[PriceSlot],
    duration_minutes: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> PriceWindow | None:
    """Highest-average window of `duration_minutes` inside [start, end), or None."""
    return _best_window(slots, duration_minutes, start, end, "max")


def _best_window(
    slots: Sequence[PriceSlot],
    duration_minutes: int,
    start: datetime | None,
    end: datetime | None,
    pick: Literal["min", "max"],
) -> PriceWindow | None:
    """Sliding window over 15-minute steps (60 if the data is hourly-only).

    Windows never cross a gap in the data. On a tie the earliest window wins.
    """
    if duration_minutes <= 0:
        raise ValueError("duration must be positive")
    step = step_minutes(slots)
    if duration_minutes % step:
        raise ValueError(f"duration must be a multiple of {step} minutes for this data")
    n = duration_minutes // step
    steps = clip(to_uniform_steps(slots, step), start, end)

    best: tuple[Decimal, list[PriceSlot], int] | None = None
    for run in contiguous_runs(steps):
        if len(run) < n:
            continue
        # Running sum: add the step entering the window, subtract the one leaving it.
        # All windows have n steps, so comparing sums is the same as comparing means.
        total = sum((s.price_eur_mwh for s in run[:n]), Decimal(0))
        for i in range(len(run) - n + 1):
            if i > 0:
                total += run[i + n - 1].price_eur_mwh - run[i - 1].price_eur_mwh
            if (
                best is None
                or (pick == "min" and total < best[0])
                or (pick == "max" and total > best[0])
            ):
                best = (total, run, i)

    if best is None:
        return None
    total, run, i = best
    window = run[i : i + n]
    return PriceWindow(
        start=window[0].ts_start,
        end=window[-1].end,
        mean_price_eur_mwh=total / n,
        step_minutes=step,
        slots=tuple(window),
    )
