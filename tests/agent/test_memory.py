from spotwise.agent.memory import SessionMemory


def test_keeps_only_last_messages() -> None:
    memory = SessionMemory(max_messages=4)
    for i in range(3):
        memory.add_turn("s", f"q{i}", f"a{i}")
    assert [m.content for m in memory.get("s")] == ["q1", "a1", "q2", "a2"]


def test_sessions_are_separate_and_unknown_is_empty() -> None:
    memory = SessionMemory()
    memory.add_turn("a", "q", "x")
    assert memory.get("b") == []
    assert len(memory.get("a")) == 2


def test_oldest_session_is_dropped() -> None:
    memory = SessionMemory(max_sessions=2)
    for sid in ("one", "two", "three"):
        memory.add_turn(sid, "q", "a")
    assert memory.get("one") == []
    assert memory.get("three") != []
