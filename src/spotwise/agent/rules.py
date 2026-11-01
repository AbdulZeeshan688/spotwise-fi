"""Rule-based agent: answers price questions with no AI model (free and deterministic).

    question → question.parse() → typed tool calls → answer from a template

It uses exactly the same tools as the LLM agent and returns the same events and
TurnResult, so /chat, the web app and the eval harness work with either agent.
Every number in an answer is copied from a tool result, so the number guardrail
holds by construction.
"""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from spotwise.agent.guardrails import find_unsupported_numbers
from spotwise.agent.prompts import REFUSAL
from spotwise.agent.question import Query, parse
from spotwise.agent.runner import ChatEvent, TurnResult
from spotwise.tools import price_tools as t
from spotwise.tools.periods import PeriodError

Out = TypeVar("Out", bound=BaseModel)

HELP = (
    "I couldn't work out what you'd like to know. I can answer things like: "
    '"What\'s the price right now?", "Cheapest 3 hours tomorrow?", '
    '"Average price last week?", "Compare this week with last week", or '
    '"What does 40 kWh cost between 22:00 and 06:00 tonight?"'
)


class _Turn:
    """Calls tools and records every call and output, like the LLM agent's history."""

    def __init__(self, ctx: t.ToolContext) -> None:
        self.ctx = ctx
        self.calls: list[dict[str, Any]] = []
        self.outputs: list[str] = []

    def call(self, fn: Callable[[t.ToolContext, Any], Out], inp: BaseModel) -> Out:
        out = fn(self.ctx, inp)
        self.calls.append({"name": fn.__name__, "args": inp.model_dump(mode="json")})
        self.outputs.append(out.model_dump_json())
        return out

    def period(self, phrase: str) -> t.PeriodOut:
        return self.call(t.resolve_period, t.PeriodInput(period=phrase))


class RuleAgent:
    """Same interface as ChatAgent (stream / ask), no LLM."""

    def __init__(self, ctx: t.ToolContext) -> None:
        self._ctx = ctx

    async def stream(self, session_id: str, question: str) -> AsyncIterator[ChatEvent]:
        """Answer, then stream it word by word so the UI behaves like with the LLM."""
        result = await asyncio.to_thread(self.answer, question)
        for call in result.tool_calls:
            yield ChatEvent("tool", {"name": call["name"], "ok": True})
        for i, word in enumerate(result.answer.split(" ")):
            yield ChatEvent("token", {"text": word if i == 0 else " " + word})
        yield ChatEvent(
            "done",
            {
                "answer": result.answer,
                "tools_used": result.tools_used,
                "unsupported_numbers": result.unsupported_numbers,
            },
            result,
        )

    async def ask(self, session_id: str, question: str) -> TurnResult:
        """Answer without streaming (evals, tests)."""
        return await asyncio.to_thread(self.answer, question)

    def answer(self, question: str) -> TurnResult:
        """Parse, call tools, write the answer."""
        turn = _Turn(self._ctx)
        try:
            text = _respond(turn, parse(question))
        except (PeriodError, ValueError) as exc:
            text = f"Sorry, I couldn't handle that time range ({exc})."
        return TurnResult(
            answer=text,
            tool_calls=turn.calls,
            tool_outputs=turn.outputs,
            unsupported_numbers=find_unsupported_numbers(text, turn.outputs, question),
        )


# --- answers per intent ---------------------------------------------------------


def _respond(turn: _Turn, q: Query) -> str:
    if q.intent == "refuse":
        return REFUSAL
    if q.intent == "help":
        return HELP
    if q.intent == "no_forecast":
        return _no_forecast(turn)
    if q.intent == "quality":
        return _quality(turn)
    if q.intent == "availability":
        return _availability(turn, q)

    if q.intent == "price_at" and not q.periods:
        return _current(turn, q)[0]

    # Everything below needs at least one period; stop early if it isn't published
    periods = [turn.period(p) for p in (q.periods or ["today"])]
    if (note := _not_published(turn, periods[0])) is not None:
        return note

    if q.intent == "compare":
        return _compare(turn, q, periods[0], periods[1])
    if q.intent == "cost":
        return _cost(turn, q, periods[0])
    if q.intent == "window":
        return _window(turn, q, periods[0])
    if q.intent == "daily":
        return _daily(turn, q, periods[0])
    if q.intent == "stats":
        return _stats(turn, q, periods[0])
    return _price_at(turn, q, periods[0])


def _no_forecast(turn: _Turn) -> str:
    avail = turn.call(t.check_data_availability, t.AvailabilityInput())
    data_end = _last_day(avail.latest_price_end)
    return (
        "I can't forecast or guess prices; I only use published day-ahead prices. "
        f"{avail.note} The latest prices I have are for {data_end}."
    )


def _quality(turn: _Turn) -> str:
    out = turn.call(t.get_data_quality, t.NoInput())
    if not out.available:
        return "No data-quality checks have been run yet, so I can't tell."
    first, last = out.days_checked[0], out.days_checked[-1]
    failing = sorted({i.day for i in out.issues if i.status == "fail"})
    warnings = Counter(i.check for i in out.issues if i.status == "warn")
    names = {"spikes": "price-spike", "staleness": "late-publication"}
    warned = ", ".join(
        f"{n} {names.get(check, check)} warnings" for check, n in sorted(warnings.items())
    )
    extra = f" Other checks raised {warned}." if warned else ""
    if not failing:
        return (
            f"No, no day from {first} to {last} had missing or duplicate prices "
            f"(data-quality status: {out.overall}).{extra}"
        )
    days = ", ".join(str(d) for d in failing)
    return f"Yes: {len(failing)} days between {first} and {last} had problems: {days}.{extra}"


def _availability(turn: _Turn, q: Query) -> str:
    if q.year is not None:
        day = date(q.year, 1, 1)
        out = turn.call(t.check_data_availability, t.AvailabilityInput(day=day))
    elif q.periods == ["tomorrow"] or not q.periods:
        out = turn.call(t.check_data_availability, t.AvailabilityInput())
    else:
        period = turn.period(q.periods[0])
        out = turn.call(t.check_data_availability, t.AvailabilityInput(day=period.start.date()))
    first = out.earliest_price_start.date() if out.earliest_price_start else None
    last = _last_day(out.latest_price_end)
    stored = f"Stored prices cover {first} to {last}." if first else "No prices are stored yet."
    if q.year is not None:
        if first and first.year <= q.year:
            return f"Yes, I have prices from {q.year}. {stored}"
        return f"No, I don't have prices for {q.year}. {stored}"
    if q.periods == [] and first:
        return f"The earliest date I have prices for is {first}. {stored}"
    return f"{out.note} {stored}"


def _not_published(turn: _Turn, period: t.PeriodOut) -> str | None:
    """Answer 'not published' if the whole period starts after the last stored price."""
    avail = turn.ctx.now().astimezone(turn.ctx.tz)
    tomorrow_start = (avail + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if period.start < tomorrow_start:
        return None
    out = turn.call(t.check_data_availability, t.AvailabilityInput(day=period.start.date()))
    if out.published:
        return None
    return f"{out.note} I won't guess prices that haven't been published."


def _window(turn: _Turn, q: Query, period: t.PeriodOut) -> str:
    minutes = q.duration_minutes or 60
    fn = t.find_cheapest_window if q.kind == "cheapest" else t.find_most_expensive_window
    out = turn.call(
        fn,
        t.WindowInput(
            start=period.start, end=period.end, duration_minutes=minutes, include_vat=q.include_vat
        ),
    )
    if not out.found or out.window_start is None or out.window_end is None:
        return f"{out.message} ({_range(period.start, period.end)})"
    word = "cheapest" if q.kind == "cheapest" else "most expensive"
    return (
        f"The {word} {_duration(minutes)} {_range(period.start, period.end)} is "
        f"{_hm(out.window_start)}–{_hm(out.window_end)} (Finnish time), averaging "
        f"{_price(out.average_price_c_kwh)} c/kWh {_vat(out.vat_included, out.vat_percent)}."
        + _coverage_note(out.coverage)
    )


def _stats(turn: _Turn, q: Query, period: t.PeriodOut) -> str:
    out = turn.call(
        t.get_price_stats,
        t.StatsInput(
            start=period.start,
            end=period.end,
            include_vat=q.include_vat,
            threshold_c_kwh=q.threshold_c_kwh,
        ),
    )
    if (
        not out.available
        or out.mean_price_c_kwh is None
        or out.min_at is None
        or out.max_at is None
    ):
        return f"{out.message} ({_range(period.start, period.end)})"
    vat = _vat(out.vat_included, out.vat_percent)
    when = _range(period.start, period.end)
    lines = [
        f"Prices {when} ({vat}): average {_price(out.mean_price_c_kwh)} c/kWh, median "
        f"{_price(out.median_price_c_kwh)} c/kWh, lowest {_price(out.min_price_c_kwh)} c/kWh "
        f"({_when(out.min_at)}), highest {_price(out.max_price_c_kwh)} c/kWh ({_when(out.max_at)})."
    ]
    if out.negative_slots:
        first = ", ".join(_when(ts) for ts in out.negative_slot_starts[:5])
        lines.append(
            f"There were {out.negative_slots} negative {out.slot_minutes}-minute slots "
            f"(first: {first})."
        )
    else:
        lines.append("There were no negative prices.")
    if out.hours_above_threshold is not None:
        lines.append(
            f"The price was above {out.threshold_c_kwh} c/kWh "
            f"for {out.hours_above_threshold} hours."
        )
    return " ".join(lines) + _coverage_note(out.coverage)


def _daily(turn: _Turn, q: Query, period: t.PeriodOut) -> str:
    out = turn.call(
        t.get_daily_averages,
        t.RangeInput(start=period.start, end=period.end, include_vat=q.include_vat),
    )
    if not out.available or out.cheapest_day is None or out.most_expensive_day is None:
        return f"{out.message} ({_range(period.start, period.end)})"
    vat = _vat(out.vat_included, out.vat_percent)
    if q.unsupported == "weekday_weekend":
        days = "; ".join(f"{d.day}: {_price(d.mean_price_c_kwh)}" for d in out.days)
        return (
            "I can't average weekdays and weekends separately yet, so here are the daily "
            f"averages {_range(period.start, period.end)} in c/kWh {vat}: {days}."
        )
    day = out.cheapest_day if q.kind == "cheapest" else out.most_expensive_day
    word = "cheapest" if q.kind == "cheapest" else "most expensive"
    return (
        f"The {word} day {_range(period.start, period.end)} was {day.day}, with an average of "
        f"{_price(day.mean_price_c_kwh)} c/kWh {vat}." + _coverage_note(out.coverage)
    )


def _compare(turn: _Turn, q: Query, a: t.PeriodOut, b: t.PeriodOut) -> str:
    out = turn.call(
        t.compare_periods,
        t.CompareInput(
            a=t.RangeInput(start=a.start, end=a.end, include_vat=q.include_vat),
            b=t.RangeInput(start=b.start, end=b.end, include_vat=q.include_vat),
        ),
    )
    if not out.available or out.difference_c_kwh is None:
        return f"{out.message}"
    mean_a, mean_b = out.period_a.mean_price_c_kwh, out.period_b.mean_price_c_kwh
    direction = "cheaper" if out.difference_c_kwh < 0 else "more expensive"
    if out.difference_c_kwh == 0:
        direction = "the same price as"
        change = ""
    else:
        change = f" ({_signed(out.difference_c_kwh)} c/kWh"
        change += f", {_signed(out.percent_change)} %)" if out.percent_change is not None else ")"
    partial = ""
    if not (out.period_a.coverage.complete and out.period_b.coverage.complete):
        partial = (
            " Note: at least one period only has partial data, so its average covers the "
            "available days."
        )
    return (
        f"{_cap(_range(b.start, b.end))} averaged {_price(mean_b)} c/kWh, versus {_price(mean_a)} "
        f"c/kWh {_range(a.start, a.end)} ({_vat(out.vat_included, out.vat_percent)}). "
        f"So it was {direction}{'' if direction.startswith('the same') else ' than that'}{change}."
        + partial
    )


def _cost(turn: _Turn, q: Query, period: t.PeriodOut) -> str:
    assert q.kwh is not None
    if q.wants_both_windows:
        minutes = q.duration_minutes or 180
        parts = []
        for fn, word in (
            (t.find_cheapest_window, "cheapest"),
            (t.find_most_expensive_window, "most expensive"),
        ):
            w = turn.call(
                fn, t.WindowInput(start=period.start, end=period.end, duration_minutes=minutes)
            )
            if not w.found or w.window_start is None or w.window_end is None:
                return f"{w.message} ({_range(period.start, period.end)})"
            cost = turn.call(
                t.estimate_cost, t.CostInput(start=w.window_start, end=w.window_end, kwh=q.kwh)
            )
            parts.append(
                f"in the {word} {_duration(minutes)} ({_hm(w.window_start)}–{_hm(w.window_end)}) "
                f"it costs {_eur(cost.cost_eur_incl_vat)} € incl. VAT"
            )
        return (
            f"Using {q.kwh} kWh {_range(period.start, period.end)}: {parts[0]}, and {parts[1]}. "
            "The difference between those two costs is what you'd save."
        )
    start, end, where = period.start, period.end, ""
    if q.use_window and q.duration_minutes is not None:
        fn = t.find_cheapest_window if q.kind == "cheapest" else t.find_most_expensive_window
        w = turn.call(
            fn,
            t.WindowInput(start=period.start, end=period.end, duration_minutes=q.duration_minutes),
        )
        if not w.found or w.window_start is None or w.window_end is None:
            return f"{w.message} ({_range(period.start, period.end)})"
        start, end = w.window_start, w.window_end
        word = "cheapest" if q.kind == "cheapest" else "most expensive"
        where = (
            f" in the {word} {_duration(q.duration_minutes)} ({_range(period.start, period.end)})"
        )
    out = turn.call(t.estimate_cost, t.CostInput(start=start, end=end, kwh=q.kwh))
    if not out.available:
        return f"{out.message}"
    excl, incl = _eur(out.cost_eur_excl_vat), _eur(out.cost_eur_incl_vat)
    span = f"{_when(start)}–{_hm(end)}"
    first, second = (f"{excl} € excl. VAT", f"{incl} € incl. {out.vat_percent}% VAT")
    if q.include_vat:
        first, second = second, first
    return (
        f"Using {q.kwh} kWh evenly{where}, {span} (Finnish time), costs {first} ({second}), "
        f"at an average of {_price(out.average_price_c_kwh_excl_vat)} c/kWh excl. VAT. "
        "Transfer fees and electricity tax are not included."
    )


def _current(turn: _Turn, q: Query) -> tuple[str, Decimal | None]:
    """The price of the slot running now: (answer text, price in c/kWh)."""
    now = turn.call(t.get_current_price, t.NoInput())
    if not now.available or now.slot_start is None or now.slot_end is None:
        return f"{now.message}", None
    price = now.price_c_kwh_incl_vat if q.include_vat else now.price_c_kwh_excl_vat
    text = (
        f"Right now ({_when(now.slot_start)}–{_hm(now.slot_end)} Finnish time) the price is "
        f"{_price(price)} c/kWh {_vat(q.include_vat, now.vat_percent)}."
    )
    return text, price


def _price_at(turn: _Turn, q: Query, period: t.PeriodOut) -> str:
    """Price at a given time, or 'now compared with the period average'."""
    if period.end - period.start <= timedelta(hours=2):
        out = turn.call(
            t.get_prices,
            t.PricesInput(
                start=period.start, end=period.end, include_vat=q.include_vat, resolution=15
            ),
        )
        if not out.available or not out.prices:
            return f"{out.message} ({_range(period.start, period.end)})"
        p = out.prices[0]
        return (
            f"The price {_when(p.start)} (Finnish time) is {_price(p.price_c_kwh)} c/kWh "
            f"{_vat(out.vat_included, out.vat_percent)}."
        )
    text, current = _current(turn, q)
    stats = turn.call(
        t.get_price_stats,
        t.StatsInput(start=period.start, end=period.end, include_vat=q.include_vat),
    )
    if stats.mean_price_c_kwh is not None and current is not None:
        relation = "below" if current < stats.mean_price_c_kwh else "above"
        text += (
            f" The average {_range(period.start, period.end)} is "
            f"{_price(stats.mean_price_c_kwh)} c/kWh, so now is {relation} average."
        )
    return text


# --- small formatting helpers -----------------------------------------------------


def _hm(ts: datetime) -> str:
    return f"{ts:%H:%M}"


def _when(ts: datetime) -> str:
    return f"{ts:%Y-%m-%d %H:%M}"


def _range(start: datetime, end: datetime) -> str:
    """'on 2025-11-15', 'from 2025-11-10 to 2025-11-16', or '2025-11-15 18:00–08:00'."""
    if start.hour == start.minute == 0 and end.hour == end.minute == 0:
        last = (end - timedelta(minutes=1)).date()
        return f"on {start.date()}" if last == start.date() else f"from {start.date()} to {last}"
    if start.date() != end.date():
        return f"from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}"
    return f"for {start:%Y-%m-%d %H:%M}–{end:%H:%M}"


def _last_day(end: datetime | None) -> str:
    return str((end - timedelta(minutes=1)).date()) if end else "no date"


def _duration(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}-hour window" if hours != 1 else "1-hour slot"
    return f"{minutes}-minute window"


def _price(value: Decimal | None) -> str:
    """2 decimals, or 3 for tiny non-zero prices (so -0.001 doesn't show as -0.00)."""
    if value is None:
        return "n/a"
    return f"{value:.3f}" if value != 0 and abs(value) < Decimal("0.01") else f"{value:.2f}"


def _eur(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _signed(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:+}"


def _vat(included: bool, percent: Decimal) -> str:
    return f"incl. {percent}% VAT" if included else "excl. VAT"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _coverage_note(coverage: t.Coverage) -> str:
    if coverage.complete:
        return ""
    return (
        f" Note: prices exist for only {coverage.available_slots} of the "
        f"{coverage.expected_slots} slots in this range, so this uses partial data."
    )
