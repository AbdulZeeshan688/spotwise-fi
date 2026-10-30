from decimal import Decimal

from spotwise.agent.guardrails import extract_numbers, find_unsupported_numbers

TOOL = (
    '{"window_start":"2026-10-29T02:30:00+02:00","window_end":"2026-10-29T05:30:00+02:00",'
    '"average_price_c_kwh":"0.971","vat_percent":"25.5"}'
)


def test_extract_numbers_handles_commas_and_minus_signs() -> None:
    assert extract_numbers("−3,5 and 12.25 and 22-06") == [
        Decimal("3.5"),
        Decimal("12.25"),
        Decimal("22"),
        Decimal("06"),
    ]


def test_answer_with_only_tool_numbers_passes() -> None:
    answer = "Cheapest 3 h tomorrow: 02:30–05:30 on 29 Oct, 0.971 c/kWh incl. 25.5% VAT."
    assert find_unsupported_numbers(answer, [TOOL], "cheapest 3 hours?") == []


def test_rounded_tool_numbers_pass() -> None:
    assert find_unsupported_numbers("about 0.97 c/kWh", [TOOL], "") == []
    assert find_unsupported_numbers("about 1.0 c/kWh", [TOOL], "") == []


def test_invented_number_is_flagged() -> None:
    answer = "02:30–05:30 at 0.971 c/kWh, saving you 42 %."
    assert find_unsupported_numbers(answer, [TOOL], "cheapest 3 hours?") == ["42"]


def test_numbers_from_the_question_are_allowed() -> None:
    assert find_unsupported_numbers("For 40 kWh …", [TOOL], "cost of 40 kWh?") == []


def test_no_tools_means_every_number_is_unsupported() -> None:
    assert find_unsupported_numbers("It costs 7.5 c/kWh", [], "price now?") == ["7.5"]
