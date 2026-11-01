"""Golden-set schema and per-question metrics (EVAL-03). Deterministic, no LLM here."""

import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from spotwise.agent.guardrails import extract_numbers
from spotwise.agent.prompts import REFUSAL

GOLDEN_DIR = Path(__file__).parent / "golden"

CheckType = Literal["price", "eur", "percent", "count", "hours", "time", "date"]
DEFAULT_TOLERANCE: dict[str, Decimal] = {
    "price": Decimal("0.01"),  # c/kWh: allows rounding 1.255 → 1.26 or 1.25
    "eur": Decimal("0.01"),
    "percent": Decimal("0.5"),
    "hours": Decimal("0.25"),
}

# Thresholds for the regression gate (EVAL-06)
MIN_NUMERIC_ACCURACY = 0.90
MIN_REFUSAL_ACCURACY = 0.95

# USD per million tokens (input, output), from Anthropic's pricing table (Oct 2026)
MODEL_PRICES_USD: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
}

_NOT_AVAILABLE_PHRASES = (
    "not published",
    "not yet",
    "not available",
    "isn't available",
    "aren't available",
    "unavailable",
    "no data",
    "don't have",
    "do not have",
    "no prices",
    "can't",
    "cannot",
    "only have",
    "only covers",
    "from 2025",
)
_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip


class GroundTruth(BaseModel):
    fn: str
    args: dict[str, Any] = {}


class GoldenQuestion(BaseModel):
    """One golden question as written in evals/golden/*.yaml."""

    id: str
    section: str
    question: str
    expect: Literal["answer", "refusal", "not_available"] = "answer"
    expected_tools: list[str] = []
    ground_truth: GroundTruth | None = None
    checks: dict[str, CheckType] = {}
    tolerance: dict[str, Decimal] = {}
    notes: str | None = None


def load_suite(name: str = "golden") -> list[GoldenQuestion]:
    """Load evals/golden/<name>.yaml and check that ids are unique."""
    raw = yaml.safe_load((GOLDEN_DIR / f"{name}.yaml").read_text())
    questions = [GoldenQuestion.model_validate(item) for item in raw]
    ids = [q.id for q in questions]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate question ids: {sorted(duplicates)}")
    return questions


# --- single checks ----------------------------------------------------------


def is_refusal(answer: str) -> bool:
    """The agent's fixed off-topic sentence (or its core phrase)."""
    text = " ".join(answer.lower().split())
    return REFUSAL.lower() in text or "i can only help with finnish electricity" in text


def explains_not_available(answer: str) -> bool:
    """The answer says the data/forecast isn't available instead of guessing."""
    text = answer.lower().replace("’", "'")
    return any(phrase in text for phrase in _NOT_AVAILABLE_PHRASES) or is_refusal(answer)


def check_fact(answer: str, expected: Any, kind: CheckType, tolerance: Decimal | None) -> bool:
    """Does the answer contain this expected fact?"""
    if kind == "time":
        return _mentions_time(answer, str(expected))
    if kind == "date":
        return _mentions_date(answer, expected)
    value = Decimal(str(expected))
    if kind == "count" and value == 0:
        text = answer.lower()
        return bool(re.search(r"\b(no|none|zero|0)\b", text))
    tol = (
        Decimal(0)
        if kind == "count"
        else (tolerance if tolerance is not None else DEFAULT_TOLERANCE[kind])
    )
    target = abs(value)  # extract_numbers returns absolute values
    return any(abs(n - target) <= tol for n in extract_numbers(answer))


def _mentions_time(answer: str, hhmm: str) -> bool:
    hour, minute = hhmm.split(":")
    h = int(hour)
    # 02:00, 2:00, 02.00, 2.00; midnight end can be written 24:00
    variants = {f"{h:02d}:{minute}", f"{h}:{minute}", f"{h:02d}.{minute}", f"{h}.{minute}"}
    if hhmm == "00:00":
        variants |= {"24:00", "midnight"}
    return any(re.search(rf"(?<!\d){re.escape(v)}(?!\d)", answer.lower()) for v in variants)


def _mentions_date(answer: str, day: date) -> bool:
    text = answer.lower()
    month = _MONTHS[day.month - 1]
    patterns = [
        day.isoformat(),
        rf"\b{day.day}(st|nd|rd|th)?\s+(of\s+)?{month}",
        rf"{month}\s+{day.day}(st|nd|rd|th)?\b",
        rf"\b{day.day}\.\s?{day.month}\.",
    ]
    return any(re.search(p, text) for p in patterns)


# --- per-question result ----------------------------------------------------


@dataclass
class QuestionResult:
    """Everything measured for one question."""

    id: str
    section: str
    question: str
    expect: str
    answer: str
    tools_used: list[str]
    tool_correct: bool
    numeric_correct: bool | None  # None = no numeric checks for this question
    refusal_correct: bool
    failed_checks: list[str]
    unsupported_numbers: list[str]
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    judge: dict[str, Any] | None = None
    expected: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def tools_correct(expected: list[str], used: list[str]) -> bool:
    """Every expected tool (or one of its 'a|b' alternatives) was called."""
    if not expected:
        return True  # nothing required; refusals may still look things up
    return all(any(option in used for option in item.split("|")) for item in expected)


def score_question(
    q: GoldenQuestion,
    facts: dict[str, Any],
    answer: str,
    tools_used: list[str],
    unsupported_numbers: list[str],
) -> tuple[bool, bool | None, bool, list[str]]:
    """(tool_correct, numeric_correct, refusal_correct, failed_checks) for one answer."""
    failed = [
        name
        for name, kind in q.checks.items()
        if not check_fact(answer, facts[name], kind, q.tolerance.get(kind))
    ]
    numeric = None if not q.checks else not failed
    if q.expect == "refusal":
        refusal_ok = is_refusal(answer)
    elif q.expect == "not_available":
        refusal_ok = explains_not_available(answer) and not unsupported_numbers
    else:
        refusal_ok = not is_refusal(answer)  # on-topic questions must not be refused
    return tools_correct(q.expected_tools, tools_used), numeric, refusal_ok, failed


RULES_MODEL = "rules (no LLM)"


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Estimated cost in USD (0 for the rule agent), or None for an unknown model."""
    if model == RULES_MODEL:
        return Decimal(0)
    if model not in MODEL_PRICES_USD:
        return None
    price_in, price_out = MODEL_PRICES_USD[model]
    return (price_in * input_tokens + price_out * output_tokens) / 1_000_000


# --- aggregate --------------------------------------------------------------


@dataclass
class Summary:
    questions: int
    numeric_accuracy: float | None
    refusal_accuracy: float | None  # questions that should refuse / explain (F-G)
    over_refusal_rate: float | None  # on-topic questions that were refused
    tool_accuracy: float
    mean_judge_score: float | None
    median_latency_ms: float
    guardrail_flags: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    errors: int
    gate_passed: bool
    gate_reasons: list[str]


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(results: list[QuestionResult]) -> Summary:
    """Aggregate metrics and the pass/fail gate."""
    numeric = [r.numeric_correct for r in results if r.numeric_correct is not None]
    refusing = [r.refusal_correct for r in results if r.expect in ("refusal", "not_available")]
    on_topic = [not r.refusal_correct for r in results if r.expect == "answer"]
    judged = [r.judge["overall"] for r in results if r.judge and "overall" in r.judge]
    costs = [r.cost_usd for r in results]
    numeric_accuracy, refusal_accuracy = _rate(numeric), _rate(refusing)

    reasons = []
    if numeric_accuracy is not None and numeric_accuracy < MIN_NUMERIC_ACCURACY:
        reasons.append(f"numeric accuracy {numeric_accuracy:.0%} < {MIN_NUMERIC_ACCURACY:.0%}")
    if refusal_accuracy is not None and refusal_accuracy < MIN_REFUSAL_ACCURACY:
        reasons.append(f"refusal accuracy {refusal_accuracy:.0%} < {MIN_REFUSAL_ACCURACY:.0%}")
    return Summary(
        questions=len(results),
        numeric_accuracy=numeric_accuracy,
        refusal_accuracy=refusal_accuracy,
        over_refusal_rate=_rate(on_topic),
        tool_accuracy=_rate([r.tool_correct for r in results]) or 0.0,
        mean_judge_score=statistics.mean(judged) if judged else None,
        median_latency_ms=statistics.median([r.latency_ms for r in results]) if results else 0,
        guardrail_flags=sum(1 for r in results if r.unsupported_numbers),
        input_tokens=sum(r.input_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        cost_usd=sum((c for c in costs if c is not None), Decimal(0))
        if all(c is not None for c in costs)
        else None,
        errors=sum(1 for r in results if r.error),
        gate_passed=not reasons,
        gate_reasons=reasons,
    )
