from datetime import date
from decimal import Decimal

import pytest

from evals.metrics import (
    GoldenQuestion,
    QuestionResult,
    check_fact,
    cost_usd,
    explains_not_available,
    is_refusal,
    score_question,
    summarize,
    tools_correct,
)
from spotwise.agent.prompts import REFUSAL


@pytest.mark.parametrize(
    ("answer", "expected", "kind", "ok"),
    [
        ("Cheapest: 02:00–05:00", "02:00", "time", True),
        ("from 2:00 to 5:00", "02:00", "time", True),
        ("klo 2.00–5.00", "02:00", "time", True),
        ("from 12:00", "02:00", "time", False),  # 2:00 must not match inside 12:00
        ("until midnight", "00:00", "time", True),
        ("on 2025-10-26", date(2025, 10, 26), "date", True),
        ("on 26 October 2025", date(2025, 10, 26), "date", True),
        ("on October 26th", date(2025, 10, 26), "date", True),
        ("on 16 October", date(2025, 10, 26), "date", False),
        ("about 1.26 c/kWh", "1.255", "price", True),
        ("about 1.27 c/kWh", "1.255", "price", False),
        ("costs 0.50 €", "0.502", "eur", True),
        ("a 12.4% rise", "12.6", "percent", True),
        ("3 negative slots", "3", "count", True),
        ("13 negative slots", "3", "count", False),
        ("There were no negative prices.", "0", "count", True),
        ("−2,5 c/kWh", "-2.5", "price", True),  # Unicode minus and decimal comma
        ("6.5 hours above", "6.5", "hours", True),
    ],
)
def test_check_fact(answer: str, expected: object, kind: str, ok: bool) -> None:
    assert check_fact(answer, expected, kind, None) is ok  # type: ignore[arg-type]


def test_refusal_detection() -> None:
    assert is_refusal(REFUSAL)
    assert is_refusal("Sorry, I can only help with Finnish electricity spot prices.")
    assert not is_refusal("The cheapest window is 02:00–05:00.")


def test_not_available_detection() -> None:
    assert explains_not_available("Tomorrow's prices are not published yet (around 14:00).")
    assert explains_not_available("I can't forecast prices for next month.")
    assert not explains_not_available("Tomorrow's cheapest hour is 03:00.")


def test_tools_correct_with_alternatives() -> None:
    assert tools_correct(["find_cheapest_window"], ["resolve_period", "find_cheapest_window"])
    assert tools_correct(["get_prices|get_price_stats"], ["get_price_stats"])
    assert not tools_correct(["estimate_cost"], ["find_cheapest_window"])
    assert tools_correct([], ["resolve_period"])


def question(**kwargs: object) -> GoldenQuestion:
    return GoldenQuestion.model_validate({"id": "q", "section": "A", "question": "?", **kwargs})


def test_score_answer_question() -> None:
    q = question(expected_tools=["find_cheapest_window"], checks={"start": "time", "avg": "price"})
    facts = {"start": "02:00", "avg": Decimal("1.255")}
    tool_ok, numeric, refusal_ok, failed = score_question(
        q, facts, "02:00–05:00 at 1.26 c/kWh incl. VAT", ["find_cheapest_window"], []
    )
    assert (tool_ok, numeric, refusal_ok, failed) == (True, True, True, [])
    _, numeric, _, failed = score_question(q, facts, "03:00 at 1.26", ["find_cheapest_window"], [])
    assert numeric is False and failed == ["start"]


def test_on_topic_question_must_not_be_refused() -> None:
    _, _, refusal_ok, _ = score_question(question(), {}, REFUSAL, [], [])
    assert not refusal_ok


def test_not_available_fails_when_it_guesses() -> None:
    q = question(expect="not_available")
    assert score_question(q, {}, "Not published yet.", [], [])[2]
    assert not score_question(q, {}, "Not published yet, probably 5 c/kWh.", [], ["5"])[2]


def result(**kwargs: object) -> QuestionResult:
    base: dict[str, object] = {
        "id": "q", "section": "A", "question": "?", "expect": "answer", "answer": "",
        "tools_used": [], "tool_correct": True, "numeric_correct": True,
        "refusal_correct": True, "failed_checks": [], "unsupported_numbers": [],
        "latency_ms": 1000, "input_tokens": 1000, "output_tokens": 100,
        "cost_usd": Decimal("0.0001"),
    }  # fmt: skip
    return QuestionResult(**{**base, **kwargs})  # type: ignore[arg-type]


def test_gate_passes_and_fails() -> None:
    good = [result() for _ in range(9)] + [result(expect="refusal")]
    assert summarize(good).gate_passed
    bad = [result(numeric_correct=False)] + [result() for _ in range(4)]
    summary = summarize(bad)
    assert summary.numeric_accuracy == 0.8
    assert not summary.gate_passed
    assert "numeric accuracy" in summary.gate_reasons[0]


def test_cost_estimate() -> None:
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == Decimal("0.60")
    assert cost_usd("some-unknown-model", 10, 10) is None
