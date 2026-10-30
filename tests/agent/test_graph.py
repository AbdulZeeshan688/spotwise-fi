from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from spotwise.agent.graph import MAX_TOOL_CALLS, build_graph
from spotwise.agent.memory import SessionMemory
from spotwise.agent.prompts import REFUSAL, TOOL_LIMIT_MESSAGE
from spotwise.agent.runner import ChatAgent, message_text
from spotwise.tools.price_tools import ToolContext
from spotwise.tools.registry import build_tools
from tests.agent.fakes import ScriptedChatModel, tool_call
from tests.quality.helpers import HEL, at


def no_db() -> AbstractContextManager[Session]:
    raise AssertionError("this test must not touch the database")


CTX = ToolContext(no_db, "FI", HEL, Decimal("0.255"), lambda: at("2025-11-01T12:05"))


def make_agent(
    *responses: AIMessage, ctx: ToolContext = CTX
) -> tuple[ChatAgent, ScriptedChatModel]:
    llm = ScriptedChatModel(responses=list(responses), calls=[])
    return ChatAgent(build_graph(llm, build_tools(ctx)), SessionMemory()), llm


async def test_tool_call_then_answer() -> None:
    agent, llm = make_agent(
        tool_call("resolve_period", period="tomorrow"),
        AIMessage("Tomorrow is 2025-11-02, from 00:00 Finnish time."),
    )
    result = await agent.ask("s1", "What date is tomorrow?")

    assert result.answer == "Tomorrow is 2025-11-02, from 00:00 Finnish time."
    assert result.tools_used == ["resolve_period"]
    assert '"start":"2025-11-02T00:00:00+02:00"' in result.tool_outputs[0]
    assert result.unsupported_numbers == []
    # The system prompt goes first in every LLM call
    assert isinstance(llm.calls[0][0], SystemMessage)


async def test_refusal_uses_no_tools() -> None:
    agent, _ = make_agent(AIMessage(REFUSAL))
    result = await agent.ask("s1", "Who won the football match yesterday?")
    assert result.answer == REFUSAL
    assert result.tools_used == []


async def test_invented_number_is_flagged() -> None:
    agent, _ = make_agent(AIMessage("The price right now is 7.25 c/kWh."))
    result = await agent.ask("s1", "Price now?")
    assert result.unsupported_numbers == ["7.25"]


async def test_tool_errors_go_back_to_the_model() -> None:
    agent, llm = make_agent(
        tool_call("resolve_period", period="next friday"),
        AIMessage("Sorry, I can't resolve that date."),
    )
    result = await agent.ask("s1", "Prices next friday?")
    assert "Unknown period" in result.tool_outputs[0]
    assert result.answer == "Sorry, I can't resolve that date."
    assert len(llm.calls) == 2


async def test_tool_call_limit_stops_the_loop() -> None:
    calls = [
        tool_call("resolve_period", f"c{i}", period="today") for i in range(MAX_TOOL_CALLS + 1)
    ]
    agent, _ = make_agent(*calls)
    result = await agent.ask("s1", "loop forever")
    assert result.answer == TOOL_LIMIT_MESSAGE
    assert len(result.tools_used) == MAX_TOOL_CALLS + 1  # the 6th call was never executed
    assert len(result.tool_outputs) == MAX_TOOL_CALLS


async def test_memory_keeps_plain_text_of_previous_turns() -> None:
    agent, llm = make_agent(
        tool_call("resolve_period", period="today"),
        AIMessage("Today is 2025-11-01."),
        AIMessage("You asked about today."),
    )
    await agent.ask("s1", "What is today?")
    await agent.ask("s1", "What did I ask?")
    sent = llm.calls[-1][1:]  # skip the system prompt
    assert [type(m) for m in sent] == [HumanMessage, AIMessage, HumanMessage]
    assert message_text(sent[1]) == "Today is 2025-11-01."


async def test_stream_yields_tokens_tool_and_done() -> None:
    agent, _ = make_agent(
        tool_call("resolve_period", period="today"),
        AIMessage("Today is 2025-11-01."),
    )
    events = [event async for event in agent.stream("s1", "What is today?")]
    kinds = [e.kind for e in events]
    assert kinds[0] == "tool" and kinds[-1] == "done"
    tokens = "".join(e.data["text"] for e in events if e.kind == "token")
    assert tokens.strip() == "Today is 2025-11-01."
    assert events[-1].data["tools_used"] == ["resolve_period"]


@pytest.mark.db
async def test_full_flow_with_real_tools(ctx: Any) -> None:
    agent, _ = make_agent(
        tool_call("resolve_period", period="today"),
        tool_call(
            "find_cheapest_window",
            "c2",
            start="2025-11-01T00:00:00+02:00",
            end="2025-11-02T00:00:00+02:00",
            duration_minutes=180,
        ),
        AIMessage(
            "Cheapest 3 hours today (Finnish time): 02:00–05:00, average 1.255 c/kWh incl. VAT."
        ),
        ctx=ctx,
    )
    result = await agent.ask("s1", "Cheapest 3 hours today?")
    assert result.tools_used == ["resolve_period", "find_cheapest_window"]
    assert '"window_start":"2025-11-01T02:00:00+02:00"' in result.tool_outputs[1]
    assert result.unsupported_numbers == []
