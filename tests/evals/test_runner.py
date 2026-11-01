"""The runner end to end, with a scripted 'perfect' agent instead of a real LLM.

Also reproduces the PHASE_GUIDE check "remove VAT from a tool → accuracy drops → gate
fails", without spending money.
"""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from sqlalchemy.orm import Session

from evals.fixtures.fixture import EVAL_NOW, load_fixture
from evals.metrics import load_suite, summarize
from evals.runner import render_markdown, run_questions, validate_suite, write_report
from spotwise.agent.graph import build_graph
from spotwise.agent.memory import SessionMemory
from spotwise.agent.runner import ChatAgent
from spotwise.ingest.pipeline import upsert_prices
from spotwise.tools import price_tools
from spotwise.tools.price_tools import ToolContext
from spotwise.tools.registry import build_tools
from tests.agent.fakes import ScriptedChatModel, tool_call
from tests.quality.helpers import HEL

pytestmark = pytest.mark.db


def last_tool_json(messages: list[BaseMessage]) -> dict[str, Any]:
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    return json.loads(str(tool_messages[-1].content))


def hhmm(iso: str) -> str:
    return iso[11:16]


def call_window_tool(messages: list[BaseMessage]) -> AIMessage:
    period = last_tool_json(messages)
    return tool_call(
        "find_cheapest_window", "c2", start=period["start"], end=period["end"], duration_minutes=180
    )


def answer_window(messages: list[BaseMessage]) -> AIMessage:
    w = last_tool_json(messages)
    vat = "incl." if w["vat_included"] else "excl."
    return AIMessage(
        f"Cheapest 3 hours today ({w['searched_start'][:10]}, Finnish time): "
        f"{hhmm(w['window_start'])}–{hhmm(w['window_end'])}, average "
        f"{w['average_price_c_kwh']} c/kWh {vat} VAT."
    )


def answer_current(messages: list[BaseMessage]) -> AIMessage:
    p = last_tool_json(messages)
    return AIMessage(
        f"Right now ({hhmm(p['slot_start'])}–{hhmm(p['slot_end'])} Finnish time) the price is "
        f"{p['price_c_kwh_incl_vat']} c/kWh incl. VAT."
    )


SCRIPTS: dict[str, list[Any]] = {
    "win-001": [tool_call("resolve_period", period="today"), call_window_tool, answer_window],
    "cur-001": [tool_call("get_current_price"), answer_current],
}


@pytest.fixture
def eval_ctx(db_session: Session) -> ToolContext:
    rows = load_fixture()
    upsert_prices(db_session, [r.slot for r in rows], "FI", "porssisahko")
    return ToolContext(
        lambda: nullcontext(db_session), "FI", HEL, Decimal("0.255"), lambda: EVAL_NOW
    )


def run(ctx: ToolContext) -> list[Any]:
    questions = [q for q in load_suite("golden") if q.id in SCRIPTS]
    facts = validate_suite(questions)
    tools = build_tools(ctx)
    agents: Iterator[ChatAgent] = (
        ChatAgent(
            build_graph(ScriptedChatModel(responses=list(SCRIPTS[q.id]), calls=[]), tools),
            SessionMemory(),
        )
        for q in questions
    )
    factory: Callable[[], ChatAgent] = agents.__next__
    return asyncio.run(run_questions(questions, facts, factory, None, "claude-haiku-5-5", None))


def test_correct_agent_passes(eval_ctx: ToolContext, tmp_path: Path) -> None:
    results = run(eval_ctx)
    assert [r.numeric_correct for r in results] == [True, True], [r.answer for r in results]
    assert all(r.tool_correct and r.refusal_correct for r in results)
    assert all(not r.unsupported_numbers for r in results)
    summary = summarize(results)
    assert summary.gate_passed

    md_path, json_path = write_report(results, summary, _meta(), tmp_path)
    assert "| Numeric accuracy (A–E) | 100% |" in md_path.read_text()
    assert json.loads(json_path.read_text())["summary"]["gate_passed"] is True


def test_removing_vat_from_the_tools_fails_the_gate(
    eval_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a bug: the tools ignore include_vat and always return prices without VAT
    real = price_tools.to_consumer_slots
    real_price = price_tools.consumer_price_c_kwh
    monkeypatch.setattr(price_tools, "to_consumer_slots", lambda s, vat, rate: real(s, False, rate))
    monkeypatch.setattr(
        price_tools, "consumer_price_c_kwh", lambda p, vat, rate: real_price(p, False, rate)
    )
    results = run(eval_ctx)
    summary = summarize(results)
    assert summary.numeric_accuracy == 0.0
    assert not summary.gate_passed
    assert "avg_price" in results[1].failed_checks or "price" in results[0].failed_checks


def test_markdown_lists_failures() -> None:
    from evals.metrics import QuestionResult

    bad = QuestionResult(
        id="x", section="B", question="Q?", expect="answer", answer="A.", tools_used=[],
        tool_correct=False, numeric_correct=False, refusal_correct=True,
        failed_checks=["window_start"], unsupported_numbers=["9"], latency_ms=5,
        input_tokens=0, output_tokens=0, cost_usd=None,
    )  # fmt: skip
    text = render_markdown([bad], summarize([bad]), _meta())
    assert "## Failures in detail" in text and "window_start" in text and "Gate: FAILED" in text


def _meta() -> dict[str, Any]:
    return {
        "suite": "golden", "started_at": "now", "model": "m", "judge_model": None,
        "eval_now": EVAL_NOW.isoformat(), "fixture": "x", "questions": 2,
    }  # fmt: skip
