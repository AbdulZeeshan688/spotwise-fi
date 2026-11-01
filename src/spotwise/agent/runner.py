"""Run one chat turn: stream tokens, then check the answer with the guardrail."""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from spotwise.agent.guardrails import find_unsupported_numbers
from spotwise.agent.memory import SessionMemory

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """Everything about one answered question (also used by the eval runner)."""

    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # name + args
    tool_outputs: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def tools_used(self) -> list[str]:
        return [call["name"] for call in self.tool_calls]


@dataclass(frozen=True)
class ChatEvent:
    """One streamed event: a text token, a finished tool call, or the final result."""

    kind: Literal["token", "tool", "done"]
    data: dict[str, Any]
    result: TurnResult | None = None


class Agent(Protocol):
    """What /chat and the eval runner need: the LLM agent and the rule agent both fit."""

    def stream(self, session_id: str, question: str) -> AsyncIterator["ChatEvent"]: ...

    async def ask(self, session_id: str, question: str) -> "TurnResult": ...


class ChatAgent:
    """The LLM agent: compiled graph plus session memory and tracing callbacks."""

    def __init__(
        self,
        graph: CompiledStateGraph[Any],
        memory: SessionMemory,
        callbacks: Sequence[BaseCallbackHandler] = (),
    ) -> None:
        self._graph = graph
        self._memory = memory
        self._callbacks = list(callbacks)

    async def stream(self, session_id: str, question: str) -> AsyncIterator[ChatEvent]:
        """Answer a question, yielding tokens as they arrive and a final 'done' event."""
        history = self._memory.get(session_id)
        inputs = {"messages": [*history, HumanMessage(question)]}
        config: RunnableConfig = {
            "callbacks": self._callbacks,
            "recursion_limit": 25,
            "metadata": {"session_id": session_id},
        }
        final_messages: list[BaseMessage] = []
        # With two stream modes, LangGraph yields (mode, chunk) pairs:
        # "messages" → (message or token chunk, metadata); "values" → full graph state
        async for item in self._graph.astream(inputs, config, stream_mode=["messages", "values"]):
            mode, chunk = cast(tuple[str, Any], item)
            if mode == "values":
                final_messages = chunk["messages"]
                continue
            message, metadata = cast(tuple[BaseMessage, dict[str, Any]], chunk)
            if isinstance(message, AIMessageChunk) and metadata.get("langgraph_node") == "agent":
                if text := message_text(message):
                    yield ChatEvent("token", {"text": text})
            elif isinstance(message, ToolMessage):
                yield ChatEvent("tool", {"name": message.name, "ok": message.status != "error"})

        result = _turn_result(final_messages[len(history) + 1 :], question)
        if result.unsupported_numbers:
            logger.warning(
                "Guardrail: numbers not found in tool results: %s", result.unsupported_numbers
            )
        self._memory.add_turn(session_id, question, result.answer)
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
        """Answer without streaming (used by evals and tests)."""
        async for event in self.stream(session_id, question):
            if event.result is not None:
                return event.result
        raise RuntimeError("agent finished without a result")


def message_text(message: BaseMessage) -> str:
    """The visible text of a message (Anthropic content can be a list of blocks)."""
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block["text"]
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text" and "text" in block
    )


def _turn_result(turn: Sequence[BaseMessage], question: str) -> TurnResult:
    answers = [m for m in turn if isinstance(m, AIMessage) and message_text(m).strip()]
    answer = message_text(answers[-1]).strip() if answers else ""
    tool_calls = [
        {"name": call["name"], "args": call["args"]}
        for m in turn
        if isinstance(m, AIMessage)
        for call in m.tool_calls
    ]
    tool_outputs = [message_text(m) for m in turn if isinstance(m, ToolMessage)]
    usage = [m.usage_metadata for m in turn if isinstance(m, AIMessage) and m.usage_metadata]
    return TurnResult(
        answer=answer,
        tool_calls=tool_calls,
        tool_outputs=tool_outputs,
        unsupported_numbers=find_unsupported_numbers(answer, tool_outputs, question),
        input_tokens=sum(u["input_tokens"] for u in usage),
        output_tokens=sum(u["output_tokens"] for u in usage),
    )
