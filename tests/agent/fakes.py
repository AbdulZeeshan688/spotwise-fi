"""A scripted chat model: replays prepared AIMessages, streaming them like a real LLM."""

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable


def tool_call(name: str, call_id: str = "call_1", **args: Any) -> AIMessage:
    """An AIMessage asking for one tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# A response is a fixed AIMessage, or a function that builds one from the conversation
# (e.g. to quote the last tool result, like a well-behaved model would).
Response = AIMessage | Callable[[list[BaseMessage]], AIMessage]


class ScriptedChatModel(BaseChatModel):
    """Returns `responses` in order; records the messages it was called with."""

    responses: list[Any]  # Response items; Any so pydantic doesn't coerce functions
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, AIMessage]:
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of responses")
        response = self.responses.pop(0)
        return response if isinstance(response, AIMessage) else response(messages)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next(messages)
        if message.tool_calls:
            chunks = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(message.tool_calls)
            ]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
            return
        for word in str(message.content).split(" "):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=word + " "))
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk
