"""Short per-session conversation memory, in RAM (API-05).

Only the plain question/answer text of finished turns is kept, not tool results or
thinking. Two reasons: numbers must come from tools in the *current* turn, and the
history we send stays append-only (we never edit earlier model output).
"""

import threading
from collections import OrderedDict, deque

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

MAX_MESSAGES = 10  # 5 question/answer pairs
MAX_SESSIONS = 1000  # oldest sessions are forgotten first


class SessionMemory:
    """Thread-safe store of the last few messages per session id."""

    def __init__(self, max_messages: int = MAX_MESSAGES, max_sessions: int = MAX_SESSIONS) -> None:
        self._max_messages = max_messages
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, deque[BaseMessage]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[BaseMessage]:
        """The stored messages for a session, oldest first."""
        with self._lock:
            return list(self._sessions.get(session_id, ()))

    def add_turn(self, session_id: str, question: str, answer: str) -> None:
        """Remember one question and its answer."""
        with self._lock:
            history = self._sessions.pop(session_id, None)
            if history is None:
                history = deque(maxlen=self._max_messages)
            history.extend([HumanMessage(question), AIMessage(answer)])
            self._sessions[session_id] = history  # move to the "most recent" end
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
