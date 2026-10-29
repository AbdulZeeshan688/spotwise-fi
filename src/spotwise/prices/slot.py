"""The PriceSlot type and helpers to turn slots into an even, gap-aware series."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class PriceSlot:
    """One price: UTC start, slot length in minutes, €/MWh excluding VAT."""

    ts_start: datetime
    resolution_minutes: int
    price_eur_mwh: Decimal

    @property
    def end(self) -> datetime:
        """UTC end of the slot (exclusive)."""
        return self.ts_start + timedelta(minutes=self.resolution_minutes)


def step_minutes(slots: Iterable[PriceSlot]) -> int:
    """15 if any slot is a quarter hour, else 60 (hourly-only data)."""
    return 15 if any(s.resolution_minutes == 15 for s in slots) else 60


def to_uniform_steps(slots: Iterable[PriceSlot], step: int) -> list[PriceSlot]:
    """Sorted slots of exactly `step` minutes. An hourly slot becomes four equal quarters
    when step is 15 (the market price was the same for the whole hour)."""
    result = []
    for slot in sorted(slots, key=lambda s: s.ts_start):
        if slot.resolution_minutes % step:
            raise ValueError(
                f"cannot split a {slot.resolution_minutes}-min slot into {step}-min steps"
            )
        for i in range(slot.resolution_minutes // step):
            result.append(
                PriceSlot(slot.ts_start + timedelta(minutes=i * step), step, slot.price_eur_mwh)
            )
    return result


def contiguous_runs(steps: list[PriceSlot]) -> list[list[PriceSlot]]:
    """Split sorted, uniform steps wherever there is a gap in time."""
    runs: list[list[PriceSlot]] = []
    for step in steps:
        if runs and runs[-1][-1].end == step.ts_start:
            runs[-1].append(step)
        else:
            runs.append([step])
    return runs


def clip(
    steps: Iterable[PriceSlot], start: datetime | None, end: datetime | None
) -> list[PriceSlot]:
    """Keep steps that lie fully inside [start, end); None means unbounded."""
    return [
        s for s in steps if (start is None or s.ts_start >= start) and (end is None or s.end <= end)
    ]
