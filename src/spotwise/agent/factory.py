"""Build the app-wide agent from config: free rule-based (default) or Claude."""

from functools import lru_cache

from spotwise.agent.memory import SessionMemory
from spotwise.agent.rules import RuleAgent
from spotwise.agent.runner import Agent, ChatAgent
from spotwise.config import get_settings
from spotwise.tools.price_tools import ToolContext


@lru_cache
def get_chat_agent() -> Agent:
    """The agent for /chat, built on first use.

    AGENT_MODE=rules (default) needs no API key and costs nothing. AGENT_MODE=llm uses
    Claude and raises LLMNotConfiguredError when LLM_MODEL / ANTHROPIC_API_KEY are missing.
    """
    settings = get_settings()
    ctx = ToolContext.from_settings(settings)
    if settings.agent_mode == "rules":
        return RuleAgent(ctx)
    # Imported here so the free mode never loads the LLM stack
    from spotwise.agent.graph import build_graph, build_llm
    from spotwise.agent.tracing import tracing_callbacks
    from spotwise.tools.registry import build_tools

    graph = build_graph(build_llm(settings), build_tools(ctx))
    return ChatAgent(graph, SessionMemory(), tracing_callbacks(settings))
