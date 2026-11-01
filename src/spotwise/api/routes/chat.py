"""POST /chat (API-05): the agent's answer streamed as Server-Sent Events.

Events, in order:
  session  {"session_id"}                       send it back next time for memory
  token    {"text"}                             a piece of the answer
  tool     {"name", "ok"}                       a tool finished (for a "checking…" UI)
  done     {"answer", "tools_used", "unsupported_numbers"}
  error    {"message"}                          instead of done, if something broke
The `done.answer` is the final text; show it instead of the streamed tokens at the end.
"""

import logging
import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from spotwise.agent.factory import get_chat_agent as build_chat_agent
from spotwise.agent.graph import LLMNotConfiguredError
from spotwise.agent.runner import Agent
from spotwise.api.ratelimit import enforce_chat_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """A question, plus the session id from an earlier answer (optional)."""

    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def get_chat_agent() -> Agent:
    """Dependency: the agent, or 503 if the LLM isn't configured."""
    try:
        return build_chat_agent()
    except LLMNotConfiguredError as exc:
        raise HTTPException(503, f"Chat is not available: {exc}") from None


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    dependencies=[Depends(enforce_chat_rate_limit)],
)
async def chat(
    body: ChatRequest, agent: Annotated[Agent, Depends(get_chat_agent)]
) -> AsyncIterable[ServerSentEvent]:
    """Stream the agent's answer to one question."""
    session_id = body.session_id or uuid.uuid4().hex
    yield ServerSentEvent(event="session", data={"session_id": session_id})
    try:
        async for event in agent.stream(session_id, body.message):
            yield ServerSentEvent(event=event.kind, data=event.data)
    except Exception:
        # Log the details, but never send internals (or keys) to the browser
        logger.exception("Chat turn failed")
        yield ServerSentEvent(
            event="error", data={"message": "Something went wrong, please try again."}
        )
