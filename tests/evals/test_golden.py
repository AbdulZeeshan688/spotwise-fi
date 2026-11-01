from collections import Counter
from datetime import date, timedelta

from evals.fixtures.fixture import FIRST_DAY, LAST_DAY, load_fixture
from evals.ground_truth import TZ
from evals.metrics import load_suite
from evals.runner import validate_suite
from spotwise.timeutils import expected_slot_count, resolution_for_day


def test_golden_suite_has_50_valid_questions() -> None:
    questions = load_suite("golden")
    assert len(questions) == 50
    assert Counter(q.section for q in questions) == {
        "A": 5, "B": 10, "C": 10, "D": 5, "E": 5, "F": 5, "G": 7, "H": 3,
    }  # fmt: skip


def test_every_ground_truth_computes_on_the_fixture() -> None:
    questions = load_suite("golden")
    facts = validate_suite(questions)
    for q in questions:
        assert set(q.checks) <= set(facts[q.id]), q.id


def test_fixture_is_complete_and_covers_both_resolutions_and_dst() -> None:
    per_day: Counter[date] = Counter(r.slot.ts_start.astimezone(TZ).date() for r in load_fixture())
    days = [FIRST_DAY + timedelta(days=n) for n in range((LAST_DAY - FIRST_DAY).days + 1)]
    assert len(days) == 60
    for day in days:
        assert per_day[day] == expected_slot_count(day, resolution_for_day(day), TZ), day
    assert per_day[date(2025, 9, 30)] == 24  # last hourly day
    assert per_day[date(2025, 10, 1)] == 96  # first 15-minute day
    assert per_day[date(2025, 10, 26)] == 100  # DST: 25 hours of quarters
    assert set(per_day) == set(days)  # nothing outside the range (no "tomorrow")
