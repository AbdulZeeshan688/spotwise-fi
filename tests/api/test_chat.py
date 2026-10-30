import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from spotwise.agent.graph import LLMNotConfiguredError, build_graph
from spotwise.agent.memory import SessionMemory
from spotwise.agent.runner import ChatAgent
from spotwise.api.main import app
from spotwise.api.ratelimit import RateLimiter, get_chat_rate_limiter
from spotwise.api.routes import chat
from spotwise.tools.registry import build_tools
from tests.agent.fakes import ScriptedChatModel, tool_call
from tests.agent.test_graph import CTX


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
def client() -> Iterator[TestClient]:
    llm = ScriptedChatModel(
        responses=[
            tool_call("resolve_period", period="today"),
            AIMessage("Today is 2025-11-01 in Finnish time."),
        ],
        calls=[],
    )
    agent = ChatAgent(build_graph(llm, build_tools(CTX)), SessionMemory())
    app.dependency_overrides[chat.get_chat_agent] = lambda: agent
    app.dependency_overrides[get_chat_rate_limiter] = lambda: RateLimiter(100)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_chat_streams_session_tokens_tool_and_done(client: TestClient) -> None:
    response = client.post("/chat", json={"message": "What is today?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "session"
    assert "tool" in kinds and "token" in kinds
    assert kinds[-1] == "done"
    done = events[-1][1]
    assert done["answer"] == "Today is 2025-11-01 in Finnish time."
    assert done["tools_used"] == ["resolve_period"]
    assert done["unsupported_numbers"] == []


def test_chat_keeps_given_session_id(client: TestClient) -> None:
    response = client.post("/chat", json={"message": "hi", "session_id": "abc-123"})
    assert parse_sse(response.text)[0] == ("session", {"session_id": "abc-123"})


def test_chat_validates_input(client: TestClient) -> None:
    assert client.post("/chat", json={"message": ""}).status_code == 422
    assert client.post("/chat", json={"message": "x" * 1001}).status_code == 422
    assert client.post("/chat", json={"message": "hi", "session_id": "bad id!"}).status_code == 422


def test_chat_rate_limit(client: TestClient) -> None:
    app.dependency_overrides[get_chat_rate_limiter] = lambda: limiter
    limiter = RateLimiter(1)
    assert client.post("/chat", json={"message": "What is today?"}).status_code == 200
    blocked = client.post("/chat", json={"message": "again"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_chat_without_llm_config_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_configured() -> ChatAgent:
        raise LLMNotConfiguredError("Set LLM_MODEL and ANTHROPIC_API_KEY in .env")

    monkeypatch.setattr(chat, "build_chat_agent", not_configured)
    app.dependency_overrides[get_chat_rate_limiter] = lambda: RateLimiter(100)
    try:
        response = TestClient(app).post("/chat", json={"message": "hi"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "LLM_MODEL" in response.json()["detail"]
