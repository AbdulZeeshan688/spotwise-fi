"""Expected answers for golden questions, computed from the fixture CSV with prices/ code.

Deliberately independent of tools/price_tools.py and of the database: if a tool gets a
bug (say it forgets VAT), the expected answers must NOT change with it, so the eval
catches the bug. Relative periods use the same pure resolve_period as the agent, with
the frozen EVAL_NOW clock.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from evals.fixtures.fixture import EVAL_NOW, FIRST_DAY, LAST_DAY, fixture_slots
from spotwise.prices.slot import PriceSlot, clip, to_uniform_steps
from spotwise.prices.stats import daily_means, estimate_cost, minutes_above, price_stats
from spotwise.prices.units import to_consumer_slots
from spotwise.prices.windows import cheapest_window, most_expensive_window
from spotwise.quality.checks import check_completeness
from spotwise.tools.periods import resolve_period

TZ = ZoneInfo("Europe/Helsinki")
VAT = Decimal("0.255")

Facts = dict[str, Any]


def _range(period: str) -> tuple[datetime, datetime]:
    p = resolve_period(period, EVAL_NOW, TZ)
    return p.start.astimezone(UTC), p.end.astimezone(UTC)


def _consumer(period: str, vat: bool) -> tuple[list[PriceSlot], datetime, datetime]:
    start, end = _range(period)
    return to_consumer_slots(fixture_slots(start, end), vat, VAT), start, end


def _hhmm(ts: datetime) -> str:
    return ts.astimezone(TZ).strftime("%H:%M")


def current_price(vat: bool = True) -> Facts:
    """Price of the slot running at EVAL_NOW."""
    now = EVAL_NOW.astimezone(UTC)
    slots = fixture_slots(now - timedelta(hours=1), now + timedelta(minutes=1))
    slot = next(s for s in slots if s.ts_start <= now < s.end)
    return {"price": to_consumer_slots([slot], vat, VAT)[0].price_eur_mwh}


def price_at(period: str, vat: bool = True) -> Facts:
    """Price of the first slot of a short period like 'today 18:00-18:15'."""
    slots, start, _ = _consumer(period, vat)
    return {"price": slots[0].price_eur_mwh}


def current_vs_period(period: str, vat: bool = True) -> Facts:
    """Current price and the mean of a period."""
    return {**current_price(vat), "mean": stats(period, vat)["mean"]}


def window(period: str, minutes: int, kind: str = "cheapest", vat: bool = True) -> Facts:
    """Cheapest / most expensive window: start, end (HH:MM) and average c/kWh."""
    slots, start, end = _consumer(period, vat)
    finder = cheapest_window if kind == "cheapest" else most_expensive_window
    w = finder(slots, minutes, start, end)
    assert w is not None, f"no {kind} window of {minutes} min in {period}"
    return {
        "window_start": _hhmm(w.start),
        "window_end": _hhmm(w.end),
        "avg_price": w.mean_price_eur_mwh,
    }


def stats(period: str, vat: bool = True, threshold: str | None = None) -> Facts:
    """Min/max with times, mean, median, negative slots, hours above a threshold."""
    slots, start, end = _consumer(period, vat)
    s = price_stats(slots)
    assert s is not None, f"no data for {period}"
    facts: Facts = {
        "min": s.min_price_eur_mwh,
        "min_at": _hhmm(s.min_at),
        "max": s.max_price_eur_mwh,
        "max_at": _hhmm(s.max_at),
        "mean": s.mean_price_eur_mwh,
        "median": s.median_price_eur_mwh,
        "negative_count": s.negative_steps,
    }
    if threshold is not None:
        steps = clip(to_uniform_steps(slots, s.step_minutes), start, end)
        facts["hours_above"] = Decimal(minutes_above(steps, Decimal(threshold))) / 60
    return facts


def daily_extreme(period: str, which: str, vat: bool = True) -> Facts:
    """The cheapest ('min') or most expensive ('max') complete day and its mean."""
    slots, _, _ = _consumer(period, vat)
    means = daily_means(slots, TZ)
    pick = min if which == "min" else max
    best = pick(means, key=lambda m: m.mean_price_eur_mwh)
    return {"day": best.day, "mean": best.mean_price_eur_mwh}


def compare(a: str, b: str, vat: bool = True) -> Facts:
    """Means of period a and b, difference b − a and percent change."""
    mean_a, mean_b = stats(a, vat)["mean"], stats(b, vat)["mean"]
    return {
        "mean_a": mean_a,
        "mean_b": mean_b,
        "difference": mean_b - mean_a,
        "percent": (mean_b - mean_a) / abs(mean_a) * 100,
    }


def cost(period: str, kwh: str) -> Facts:
    """Euros for kwh spread evenly over the period (raw €/MWh in, VAT per slot)."""
    start, end = _range(period)
    c = estimate_cost(fixture_slots(start, end), start, end, Decimal(kwh), VAT)
    return {"cost_excl": c.cost_eur_excl_vat, "cost_incl": c.cost_eur_incl_vat}


def window_cost(period: str, minutes: int, kwh: str, kind: str = "cheapest") -> Facts:
    """Cost of kwh used in the cheapest / most expensive window of a period (incl. VAT)."""
    slots, start, end = _consumer(period, True)
    finder = cheapest_window if kind == "cheapest" else most_expensive_window
    w = finder(slots, minutes, start, end)
    assert w is not None
    c = estimate_cost(fixture_slots(w.start, w.end), w.start, w.end, Decimal(kwh), VAT)
    return {"window_start": _hhmm(w.start), "cost_incl": c.cost_eur_incl_vat}


def window_costs(period: str, minutes: int, kwh: str) -> Facts:
    """Costs in the cheapest and in the most expensive window (incl. VAT)."""
    cheap = window_cost(period, minutes, kwh, "cheapest")["cost_incl"]
    dear = window_cost(period, minutes, kwh, "most_expensive")["cost_incl"]
    return {"cheap_cost": cheap, "dear_cost": dear}


def data_range() -> Facts:
    """First and last day of the fixture."""
    return {"first_day": FIRST_DAY, "last_day": LAST_DAY}


def incomplete_days() -> Facts:
    """How many fixture days fail the completeness check (pure check, no DB)."""
    rows = fixture_slots(*_range(f"{FIRST_DAY}..{LAST_DAY}"))
    by_day: dict[date, list[PriceSlot]] = {}
    for s in rows:
        by_day.setdefault(s.ts_start.astimezone(TZ).date(), []).append(s)
    days = [FIRST_DAY + timedelta(days=n) for n in range((LAST_DAY - FIRST_DAY).days + 1)]
    failing = [d for d in days if check_completeness(d, by_day.get(d, []), TZ).status == "fail"]
    return {"missing_days": len(failing)}


GROUND_TRUTH: dict[str, Callable[..., Facts]] = {
    fn.__name__: fn
    for fn in (
        current_price,
        price_at,
        current_vs_period,
        window,
        stats,
        daily_extreme,
        compare,
        cost,
        window_cost,
        window_costs,
        data_range,
        incomplete_days,
    )
}


def compute(fn: str, args: dict[str, Any]) -> Facts:
    """Run a named ground-truth function with YAML arguments."""
    if fn not in GROUND_TRUTH:
        raise KeyError(f"unknown ground_truth fn {fn!r}; known: {sorted(GROUND_TRUTH)}")
    return GROUND_TRUTH[fn](**args)
