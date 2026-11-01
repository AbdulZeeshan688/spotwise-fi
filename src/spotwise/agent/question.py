"""Understand a price question without an AI model: text → a structured Query.

Pure functions, no database. The rule agent (rules.py) turns a Query into tool calls.
Periods come out as resolve_period phrases ("today", "2025-10", "today 18:00-08:00"),
so all date math still happens in one tested place.
"""

import calendar
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Intent = Literal[
    "refuse",  # off-topic or not allowed
    "no_forecast",  # asks for future prices we can't know
    "quality",
    "availability",
    "compare",
    "cost",
    "window",
    "daily",  # cheapest / most expensive day, per-day averages
    "stats",
    "price_at",  # current price or price at a given time
    "help",  # on topic, but we couldn't understand it
]

MONTHS = {
    m: i
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"],
        start=1,
    )
}  # fmt: skip
_MONTH = "(" + "|".join(MONTHS) + ")"

# Finnish words and common shorthand → English, so the rules below stay simple
_REPLACEMENTS = [
    (r"\b2day\b", "today"),
    (r"\b(2moro|tmrw|tomoz|2morrow)\b", "tomorrow"),
    (r"\bnyt\b", "now"),
    (r"\btänään\b", "today"),
    (r"\bhuomenna\b", "tomorrow"),
    (r"\beilen\b", "yesterday"),
    (r"\bhalvin\b", "cheapest"),
    (r"\bkallein\b", "most expensive"),
    (r"\bilman alv\b", "without vat"),
    (r"\bsähkö\w*", "electricity"),
    (r"\bhint\w*", "price"),
    (r"(\d)\s*h\b", r"\1 hours"),  # "3h" → "3 hours"
]

_TOPIC_WORDS = (
    "price", "cost", "cheap", "expensive", "kwh", "electric", "spot", "charg", "sauna",
    "dishwasher", "laundry", "washing", " ev", "negative", "average", "median", "publish",
    "data", "window", "vat", "€", "euro", "compare", "tariff", "energy", "power",
)  # fmt: skip
_OTHER_AREAS = (
    "sweden", "swedish", "norway", "norwegian", "denmark", "danish", "estonia", "germany",
    "german", "france", "baltic", "se1", "se2", "se3", "se4", "no1", "dk1", "ee ",
)  # fmt: skip


@dataclass
class Query:
    """What the question asks for."""

    intent: Intent
    periods: list[str] = field(default_factory=list)  # resolve_period phrases
    duration_minutes: int | None = None
    kwh: Decimal | None = None
    include_vat: bool = True
    kind: Literal["cheapest", "most_expensive"] = "cheapest"
    threshold_c_kwh: Decimal | None = None
    use_window: bool = False  # cost of the cheapest / most expensive window
    wants_both_windows: bool = False  # "save by using cheapest instead of most expensive"
    year: int | None = None  # "do you have data for 2020?"
    unsupported: str | None = None  # a part we can't do (e.g. weekday vs weekend)


def normalise(text: str) -> str:
    """Lower case, Finnish/shorthand → English, tidy spaces."""
    t = " " + text.lower().replace("–", "-").replace("’", "'") + " "
    for pattern, repl in _REPLACEMENTS:
        t = re.sub(pattern, repl, t)
    return " ".join(t.split())


def parse(question: str) -> Query:
    """Classify a question and pull out periods, durations, kWh and options."""
    t = normalise(question)
    include_vat = not re.search(r"without vat|excl\.? vat|excluding vat|no vat|ex vat", t)

    # --- things we never do ---------------------------------------------------
    if re.search(r"system prompt|your prompt|your instructions|ignore (your|all|previous)", t):
        if "guess" in t:
            return Query("no_forecast", ["tomorrow"])
        return Query("refuse")
    if re.search(r"\b(guess|forecast|predict|prediction)\b|next (month|year|week)", t):
        return Query("no_forecast", ["tomorrow"])
    if any(area in t + " " for area in _OTHER_AREAS):
        return Query("refuse")
    if re.search(r"\b(company|companies|provider|supplier|retailer|switch to|which contract)\b", t):
        return Query("refuse")
    if not any(word in " " + t for word in _TOPIC_WORDS) and not re.search(
        r"\b(now|right now|at the moment)\b.*\b(cost|price)|\bcheapest\b", t
    ):
        return Query("refuse")

    periods = find_periods(t)
    duration = find_duration(t)
    kwh = _number_before(t, r"\s*kwh")
    kind: Literal["cheapest", "most_expensive"] = (
        "most_expensive" if re.search(r"most expensive|priciest|highest", t) else "cheapest"
    )

    # --- data questions ---------------------------------------------------------
    if re.search(r"\bmissing\b|\bgaps?\b|data quality|\bduplicat", t):
        return Query("quality")
    year_match = re.search(r"\bdata for (\d{4})\b|\b(\d{4})\b.*\bdata\b|\bdata\b.*\b(\d{4})\b", t)
    if re.search(r"earliest|first date|how far back|oldest", t) or (
        "do you have" in t and year_match
    ):
        year = next((int(g) for g in year_match.groups() if g), None) if year_match else None
        return Query("availability", year=year)
    if re.search(r"\bpublished\b|\bavailable yet\b|\bout yet\b", t):
        return Query("availability", periods or ["tomorrow"])

    # --- comparisons ------------------------------------------------------------
    if re.search(r"\bcompare|\bvs\.?\b|\bversus\b|\bthan\b|change between", t) and kwh is None:
        if re.search(r"\bweekends?\b", t):
            return Query(
                "daily", periods[:1], include_vat=include_vat, unsupported="weekday_weekend"
            )
        if re.search(r"same weekday (one|a|1) week (earlier|before)|same day last week", t):
            periods = periods[:1] + [_week_earlier(periods[0] if periods else "yesterday")]
        if len(periods) >= 2:
            # "between A and B" → A is the reference; otherwise the subject comes first
            first, second = periods[0], periods[1]
            a, b = (first, second) if "between" in t else (second, first)
            return Query("compare", [a, b], include_vat=include_vat)

    # --- costs ------------------------------------------------------------------
    if kwh is not None and re.search(r"cost|how much|price|save|€|euro|pay", t):
        if "cheapest" in t and "most expensive" in t:
            return Query(
                "cost", periods[:1] or ["today"], duration, kwh, include_vat,
                wants_both_windows=True,
            )  # fmt: skip
        if re.search(r"cheapest|most expensive", t):
            return Query(
                "cost", periods[:1] or ["today"], duration or 180, kwh, include_vat, kind,
                use_window=True,
            )  # fmt: skip
        return Query("cost", periods[:1] or ["today"], duration, kwh, include_vat)

    # --- per-day questions --------------------------------------------------------
    if re.search(r"(cheapest|most expensive|priciest|lowest|highest) day|daily average", t):
        return Query("daily", periods[:1] or ["last 30 days"], include_vat=include_vat, kind=kind)

    # --- windows ------------------------------------------------------------------
    is_window = re.search(
        r"\b(cheapest|most expensive|best time|when should|when to|when's the best|"
        r"when is the best|priciest)\b",
        t,
    )
    asks_stats = re.search(r"\b(highest|lowest|min|max|average|mean|median|negative)\b", t) or (
        "cheapest" in t and "most expensive" in t  # both ends = statistics, not one window
    )
    if is_window and not asks_stats:
        return Query("window", periods[:1] or ["today"], duration or 60, None, include_vat, kind)

    # --- statistics -----------------------------------------------------------------
    threshold = _number_after(t, r"\b(?:above|over|more than|higher than)\s*")
    if asks_stats or threshold is not None or re.search(r"how many", t):
        if re.search(r"\bnow\b|right now|at the moment", t):
            return Query("price_at", ["today"], include_vat=include_vat)  # now vs average
        return Query(
            "stats", periods[:1] or ["today"], include_vat=include_vat, threshold_c_kwh=threshold
        )

    # --- single prices --------------------------------------------------------------
    if re.search(r"\bnow\b|right now|at the moment|currently|\bat \d{1,2}[:.]\d{2}", t) or (
        periods and re.search(r"\b\d{1,2}:\d{2}-\d{1,2}:\d{2}\b", periods[0])
    ):
        return Query("price_at", periods[:1], include_vat=include_vat)

    if periods and re.search(r"price|cost", t):
        return Query("stats", periods[:1], include_vat=include_vat)
    return Query("help")


# --- periods -------------------------------------------------------------------------


def find_periods(t: str) -> list[str]:
    """resolve_period phrases found in normalised text, in the order they appear."""
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []

    def add(match: re.Match[str], phrase: str) -> None:
        span = match.span()
        if any(s < span[1] and span[0] < e for s, e in taken):
            return  # already covered by a longer pattern
        taken.append(span)
        found.append((span[0], phrase))

    # Time ranges first (they also contain day words)
    for m in re.finditer(
        r"between (\d{1,2})[:.](\d{2}) (today|tomorrow|yesterday) and (\d{1,2})[:.](\d{2})"
        r" (today|tomorrow)",
        t,
    ):
        add(m, f"{m[3]} {_hhmm(m[1], m[2])}-{_hhmm(m[4], m[5])}")
    for m in re.finditer(
        r"(?:between )?(\d{1,2})[:.](\d{2}) ?(?:and|-|to|until) ?(\d{1,2})[:.](\d{2})", t
    ):
        add(m, f"{_day_word_near(t, m)} {_hhmm(m[1], m[2])}-{_hhmm(m[3], m[4])}")
    for m in re.finditer(r"\bat (\d{1,2})[:.](\d{2})", t):
        minutes = _single_slot_minutes(t)
        start = int(m[1]) * 60 + int(m[2])
        end = (start + minutes) % (24 * 60)
        add(m, f"{_day_word_near(t, m)} {_hhmm(m[1], m[2])}-{end // 60:02d}:{end % 60:02d}")

    # Explicit dates and months
    for m in re.finditer(r"first and second half of " + _MONTH + r" (\d{4})", t):
        month, year = MONTHS[m[1]], int(m[2])
        add(m, f"{year}-{month:02d}-01..{year}-{month:02d}-15")
        found.append(
            (m.end(), f"{year}-{month:02d}-16..{year}-{month:02d}-{_last_day(year, month)}")
        )
    for m in re.finditer(r"first two weeks of " + _MONTH + r" (\d{4})", t):
        month, year = MONTHS[m[1]], int(m[2])
        add(m, f"{year}-{month:02d}-01..{year}-{month:02d}-14")
    for m in re.finditer(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", t):
        add(m, f"{m[1]}..{m[2]}")
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", t):
        add(m, m[1])
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)? " + _MONTH + r",? (\d{4})", t):
        add(m, f"{m[3]}-{MONTHS[m[2]]:02d}-{int(m[1]):02d}")
    for m in re.finditer(_MONTH + r" (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})", t):
        add(m, f"{m[3]}-{MONTHS[m[1]]:02d}-{int(m[2]):02d}")
    for m in re.finditer(_MONTH + r" (\d{4})", t):
        add(m, f"{m[2]}-{MONTHS[m[1]]:02d}")
    for m in re.finditer(r"\b(\d{4}-\d{2})\b", t):
        add(m, m[1])

    # Relative words
    relative = [
        (r"\bsame week last month\b", "4 weeks ago"),
        (r"\b(this|current) week\b", "this week"),
        (r"\blast week\b", "last week"),
        (r"\b(this|current) month('s)?\b", "this month"),
        (r"\blast month\b", "last month"),
        (r"\blast (\d{1,3}) days\b", None),
        (r"\bnext (\d{1,2}) hours\b", None),
        (r"\b(\d{1,3}) days ago\b", None),
        (r"\byesterday\b|\blast night\b", "yesterday"),
        (r"\btomorrow\b", "tomorrow"),
        (r"\btoday\b|\btonight\b|\bthis (morning|evening|afternoon)\b", "today"),
    ]
    for pattern, phrase in relative:
        for m in re.finditer(pattern, t):
            add(m, phrase or m[0])
    return [phrase for _, phrase in sorted(found)]


def find_duration(t: str) -> int | None:
    """Window length in minutes ('3 hours', '30 minutes', 'an hour'), a multiple of 15."""
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*-?\s*(hours?|hrs?)\b", t):
        minutes = float(m[1].replace(",", ".")) * 60
    elif m := re.search(r"(\d+)\s*-?\s*(minutes?|mins?)\b", t):
        minutes = float(m[1])
    elif re.search(r"half an hour", t):
        minutes = 30
    elif re.search(r"\b(an|one|1-?)\s*hour\b|\bhour\b|\bslot\b", t):
        minutes = 60
    else:
        return None
    return max(15, round(minutes / 15) * 15)


def _single_slot_minutes(t: str) -> int:
    """'at 19:00 (1 hour)' → 60; a bare 'at 18:00' means one 15-minute slot."""
    duration = re.search(r"\((\d+(?:[.,]\d+)?)\s*hours?\)|for (\d+(?:[.,]\d+)?)\s*hours?", t)
    if duration:
        value = next(g for g in duration.groups() if g)
        return round(float(value.replace(",", ".")) * 60)
    return 15


def _day_word_near(t: str, m: re.Match[str]) -> str:
    """The day a time belongs to: look around the time for today/tomorrow/yesterday."""
    window = t[max(0, m.start() - 40) : m.end() + 40]
    if re.search(r"last night|yesterday", window):
        return "yesterday"
    if "tomorrow" in window:
        return "tomorrow"
    if date := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", window):
        return date[1]
    return "today"


def _week_earlier(period: str) -> str:
    if period == "yesterday":
        return "8 days ago"
    if period == "today":
        return "7 days ago"
    if m := re.fullmatch(r"(\d+) days ago", period):
        return f"{int(m[1]) + 7} days ago"
    return "last week"


def _hhmm(h: str, m: str) -> str:
    return f"{int(h):02d}:{m}"


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _number_before(t: str, unit: str) -> Decimal | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)" + unit, t)
    return Decimal(m[1].replace(",", ".")) if m else None


def _number_after(t: str, prefix: str) -> Decimal | None:
    m = re.search(prefix + r"(\d+(?:[.,]\d+)?)", t)
    return Decimal(m[1].replace(",", ".")) if m else None
