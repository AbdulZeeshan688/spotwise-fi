"""LangGraph agent: an LLM node that may call tools, a ToolNode, and a tool-call limit.

START → agent ─(tool calls)→ tools → agent … ─(answer)→ END
              └(more than MAX_TOOL_CALLS)→ limit → END
"""

import logging
from collections.abc import Sequence
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from spotwise.agent.prompts import SYSTEM_PROMPT, TOOL_LIMIT_MESSAGE
from spotwise.config import Settings

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 5


class LLMNotConfiguredError(RuntimeError):
    """LLM_MODEL or ANTHROPIC_API_KEY is missing."""


def build_llm(settings: Settings) -> ChatAnthropic:
    """Claude chat model from config. The model name always comes from LLM_MODEL.

    No `temperature`: the current Claude API rejects sampling parameters. Answers stay
    repeatable because all numbers come from deterministic tools.
    """
    if not settings.llm_model or settings.anthropic_api_key is None:
        raise LLMNotConfiguredError("Set LLM_MODEL and ANTHROPIC_API_KEY in .env")
    return ChatAnthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        max_tokens=4096,
        max_retries=3,
        # Short chat answers with a few tool calls don't need deep thinking
        output_config={"effort": "medium"},
    )


def build_graph(llm: BaseChatModel, tools: Sequence[BaseTool]) -> CompiledStateGraph[Any]:
    """Compile the agent graph for an LLM and a tool list."""
    llm_with_tools = llm.bind_tools(tools)

    async def agent(state: MessagesState) -> dict[str, list[BaseMessage]]:
        response = await llm_with_tools.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [response]}

    def limit(state: MessagesState) -> dict[str, list[BaseMessage]]:
        logger.warning("Tool-call limit (%d) reached", MAX_TOOL_CALLS)
        return {"messages": [AIMessage(TOOL_LIMIT_MESSAGE)]}

    def route(state: MessagesState) -> Literal["tools", "limit", "__end__"]:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return "__end__"  # the value of langgraph's END
        if tool_calls_this_turn(state["messages"]) > MAX_TOOL_CALLS:
            return "limit"
        return "tools"

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    # handle_tool_errors: a failing tool returns its error text to the LLM
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    graph.add_node("limit", limit)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("limit", END)
    return graph.compile()


def tool_calls_this_turn(messages: Sequence[BaseMessage]) -> int:
    """Tool calls the model made since the last user message."""
    count = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage):
            count += len(message.tool_calls)
    return count
