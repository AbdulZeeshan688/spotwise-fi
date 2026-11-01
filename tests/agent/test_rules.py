"""The rule-based agent on known test prices (tests/tools/conftest.py: now = 2025-11-01 12:05)."""

import asyncio

import pytest

from spotwise.agent.prompts import REFUSAL
from spotwise.agent.rules import RuleAgent
from spotwise.tools.price_tools import ToolContext

pytestmark = pytest.mark.db


def ask(ctx: ToolContext, question: str) -> tuple[str, list[str], list[str]]:
    result = asyncio.run(RuleAgent(ctx).ask("s", question))
    return result.answer, result.tools_used, result.unsupported_numbers


def test_current_price(ctx: ToolContext) -> None:
    answer, tools, unsupported = ask(ctx, "What's the price right now?")
    assert "12.55 c/kWh incl. 25.5% VAT" in answer
    assert "2025-11-01 12:00–12:15" in answer
    assert tools == ["get_current_price"]
    assert unsupported == []


def test_cheapest_window_states_range_and_vat(ctx: ToolContext) -> None:
    answer, tools, unsupported = ask(ctx, "When is the cheapest 3-hour window today?")
    assert "02:00–05:00" in answer and "1.26 c/kWh incl. 25.5% VAT" in answer
    assert "on 2025-11-01" in answer
    assert tools == ["resolve_period", "find_cheapest_window"]
    assert unsupported == []


def test_cost_with_and_without_vat(ctx: ToolContext) -> None:
    answer, tools, _ = ask(ctx, "How much does 40 kWh cost between 02:00 and 05:00 today?")
    assert "0.50 € incl." in answer and "0.40 € excl. VAT" in answer
    assert tools[-1] == "estimate_cost"


def test_negative_prices_and_stats(ctx: ToolContext) -> None:
    answer, _, unsupported = ask(ctx, "Were there negative prices tomorrow?")
    assert "2 negative 15-minute slots" in answer
    assert "-2.00 c/kWh" in answer  # no VAT on negative prices
    assert unsupported == []


def test_unpublished_day_is_never_guessed(ctx: ToolContext) -> None:
    answer, tools, unsupported = ask(ctx, "Cheapest 3 hours on 2025-11-03?")
    assert "not published yet" in answer and "14:00" in answer
    assert "check_data_availability" in tools
    assert unsupported == []


def test_off_topic_is_refused_without_tools(ctx: ToolContext) -> None:
    answer, tools, _ = ask(ctx, "Who won the football match yesterday?")
    assert answer == REFUSAL and tools == []


def test_forecast_is_refused_politely(ctx: ToolContext) -> None:
    answer, _, unsupported = ask(ctx, "What will the electricity price be next month?")
    assert "can't forecast" in answer and unsupported == []


def test_compare(ctx: ToolContext) -> None:
    answer, tools, unsupported = ask(ctx, "Was 2025-11-02 cheaper than 2025-11-01?")
    assert "cheaper than that" in answer
    assert tools.count("resolve_period") == 2 and "compare_periods" in tools
    assert unsupported == []


def test_stream_emits_tool_token_done(ctx: ToolContext) -> None:
    async def collect() -> list[str]:
        return [e.kind async for e in RuleAgent(ctx).stream("s", "Price now?")]

    kinds = asyncio.run(collect())
    assert kinds[0] == "tool" and "token" in kinds and kinds[-1] == "done"
