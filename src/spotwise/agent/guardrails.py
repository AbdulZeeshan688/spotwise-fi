"""Output guardrail (AGENT-04): every number in an answer must come from this turn's
tool results (or the user's own question)."""

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

# Numbers like 12, 12.5, 12,5 (Finnish decimal comma), -3.2, −3.2 (Unicode minus)
_NUMBER = re.compile(r"[-−]?\d+(?:[.,]\d+)?")

# Too common to check: "1 hour", "0 negative slots"
_ALWAYS_ALLOWED = {Decimal(0), Decimal(1)}


def extract_numbers(text: str) -> list[Decimal]:
    """All numbers in a text, as absolute values (a '-' in '22-06' is not a sign)."""
    numbers = []
    for raw in _NUMBER.findall(text):
        try:
            numbers.append(abs(Decimal(raw.replace("−", "-").replace(",", "."))))
        except InvalidOperation:
            continue
    return numbers


def find_unsupported_numbers(answer: str, tool_outputs: Iterable[str], question: str) -> list[str]:
    """Numbers in `answer` not found in the tool outputs or the question.

    A number counts as supported if a source number rounds to it, e.g. 1.26 is
    supported by a tool value of 1.255 (rounded to 2 decimals).
    """
    sources = set(extract_numbers(question)) | _ALWAYS_ALLOWED
    for output in tool_outputs:
        sources |= set(extract_numbers(output))

    unsupported = []
    for value in extract_numbers(answer):
        if not any(_matches(value, source) for source in sources):
            unsupported.append(str(value))
    return unsupported


def _matches(value: Decimal, source: Decimal) -> bool:
    if value == source:
        return True
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent > 0:
        return False
    quantum = Decimal(1).scaleb(exponent)
    return any(
        source.quantize(quantum, rounding=r) == value for r in (ROUND_HALF_UP, ROUND_HALF_EVEN)
    )
