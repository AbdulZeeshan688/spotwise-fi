"""LLM-as-judge (EVAL-04): scores answer quality against evals/rubric.md.

The judge uses its own prompt (not the agent's) and sees the tool outputs, so it can
check whether numbers were invented. Scores are a second opinion next to the
deterministic metrics, never a replacement for them.
"""

from pathlib import Path
from typing import Any, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from spotwise.config import Settings

RUBRIC = (Path(__file__).parent / "rubric.md").read_text()
MAX_TOOL_OUTPUT_CHARS = 6000  # keep the judge prompt small

JUDGE_SYSTEM = f"""You are a strict evaluator of answers from SpotWise, an assistant for \
Finnish electricity spot prices. Score the answer with the rubric below. Base every score \
only on the question, the answer and the tool outputs you are given; the tool outputs are \
the only trusted source of numbers.

{RUBRIC}"""


class JudgeScores(BaseModel):
    """The judge's scores, 1-5 each, with a one-sentence reason."""

    clarity: int = Field(ge=1, le=5)
    states_range: int = Field(ge=1, le=5)
    states_vat: int = Field(ge=1, le=5)
    no_invented_numbers: int = Field(ge=1, le=5)
    reason: str = Field(description="One sentence explaining the lowest score")

    @property
    def overall(self) -> float:
        return (self.clarity + self.states_range + self.states_vat + self.no_invented_numbers) / 4


def build_judge(settings: Settings) -> Runnable[Any, Any]:
    """Judge model from JUDGE_MODEL (falls back to LLM_MODEL), with structured output."""
    model = settings.judge_model or settings.llm_model
    if not model or settings.anthropic_api_key is None:
        raise RuntimeError("Set JUDGE_MODEL (or LLM_MODEL) and ANTHROPIC_API_KEY to use the judge")
    llm = ChatAnthropic(
        model=model,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        max_retries=3,
        output_config={"effort": "low"},
    )
    # json_schema = the API's native structured output (no forced tool call needed)
    return llm.with_structured_output(JudgeScores, method="json_schema")


def judge_answer(
    judge: Runnable[Any, Any],
    question: str,
    answer: str,
    tool_outputs: list[str],
    expect: str,
) -> JudgeScores:
    """Score one answer."""
    outputs = "\n\n".join(tool_outputs)[:MAX_TOOL_OUTPUT_CHARS] or "(no tools were called)"
    expectation = {
        "answer": "The question is on-topic and should be answered with data.",
        "refusal": "The question is off-topic; a short polite refusal is the right answer.",
        "not_available": "The data doesn't exist (yet); the right answer explains that "
        "without guessing any numbers.",
    }[expect]
    prompt = (
        f"<question>{question}</question>\n<expected_behaviour>{expectation}</expected_behaviour>\n"
        f"<tool_outputs>\n{outputs}\n</tool_outputs>\n<answer>{answer}</answer>"
    )
    result = judge.invoke([SystemMessage(JUDGE_SYSTEM), HumanMessage(prompt)])
    return cast(JudgeScores, result)
