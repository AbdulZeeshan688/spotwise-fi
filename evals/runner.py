"""Evaluation runner (EVAL-03..06).

    uv run python -m evals.runner --suite golden            # full run (real LLM, costs money)
    uv run python -m evals.runner --suite golden --limit 5  # quick smoke run
    uv run python -m evals.runner --check                   # no LLM: validate + ground truth

A run: load the frozen fixture into the eval DB → ask every question through the real
agent with a frozen clock → score with metrics.py (and the LLM judge) → write
evals/reports/<timestamp>.md + .json → exit 1 if the gate fails.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy.orm import Session

from evals.fixtures.fixture import EVAL_NOW, FIRST_DAY, LAST_DAY
from evals.fixtures.loader import load_eval_database
from evals.ground_truth import compute
from evals.judge import build_judge, judge_answer
from evals.metrics import (
    MIN_NUMERIC_ACCURACY,
    MIN_REFUSAL_ACCURACY,
    RULES_MODEL,
    GoldenQuestion,
    QuestionResult,
    Summary,
    cost_usd,
    load_suite,
    score_question,
    summarize,
)
from spotwise.agent.graph import build_graph, build_llm
from spotwise.agent.memory import SessionMemory
from spotwise.agent.rules import RuleAgent
from spotwise.agent.runner import Agent, ChatAgent
from spotwise.agent.tracing import tracing_callbacks
from spotwise.config import get_settings
from spotwise.timeutils import local_tz
from spotwise.tools.price_tools import ToolContext
from spotwise.tools.registry import TOOL_SPECS, build_tools

REPORTS_DIR = Path(__file__).parent / "reports"
logger = logging.getLogger("evals")
app = typer.Typer(add_completion=False)


def validate_suite(questions: list[GoldenQuestion]) -> dict[str, dict[str, Any]]:
    """Check tool names and compute every ground truth. Returns facts per question id."""
    known_tools = {fn.__name__ for fn, _, _ in TOOL_SPECS}
    facts: dict[str, dict[str, Any]] = {}
    for q in questions:
        for item in q.expected_tools:
            unknown = set(item.split("|")) - known_tools
            if unknown:
                raise ValueError(f"{q.id}: unknown tool(s) {sorted(unknown)}")
        if q.checks and q.ground_truth is None:
            raise ValueError(f"{q.id}: has checks but no ground_truth")
        facts[q.id] = compute(q.ground_truth.fn, q.ground_truth.args) if q.ground_truth else {}
        missing = set(q.checks) - set(facts[q.id])
        if missing:
            raise ValueError(f"{q.id}: ground truth has no {sorted(missing)}")
    return facts


async def run_questions(
    questions: list[GoldenQuestion],
    facts: dict[str, dict[str, Any]],
    agent_factory: Callable[[], Agent],
    judge: Any | None,
    model: str | None,
    judge_model: str | None,
) -> list[QuestionResult]:
    """Ask each question in a fresh session and score it."""
    results = []
    for i, q in enumerate(questions, start=1):
        agent = agent_factory()
        started = time.perf_counter()
        error = None
        try:
            turn = await agent.ask(f"eval-{q.id}", q.question)
            answer, tools, tool_outputs = turn.answer, turn.tools_used, turn.tool_outputs
            unsupported, tokens_in, tokens_out = (
                turn.unsupported_numbers,
                turn.input_tokens,
                turn.output_tokens,
            )
        except Exception as exc:  # one broken question must not stop the whole run
            logger.exception("%s failed", q.id)
            answer, tools, tool_outputs, unsupported = "", [], [], []
            tokens_in = tokens_out = 0
            error = repr(exc)
        latency_ms = int((time.perf_counter() - started) * 1000)

        tool_ok, numeric_ok, refusal_ok, failed = score_question(
            q, facts[q.id], answer, tools, unsupported
        )
        cost = cost_usd(model, tokens_in, tokens_out)
        scores = None
        if judge is not None and not error:
            try:
                scores_obj = judge_answer(judge, q.question, answer, tool_outputs, q.expect)
                scores = {**scores_obj.model_dump(), "overall": scores_obj.overall}
            except Exception as exc:
                logger.warning("judge failed for %s: %r", q.id, exc)
        results.append(
            QuestionResult(
                id=q.id,
                section=q.section,
                question=q.question,
                expect=q.expect,
                answer=answer,
                tools_used=tools,
                tool_correct=tool_ok,
                numeric_correct=numeric_ok,
                refusal_correct=refusal_ok,
                failed_checks=failed,
                unsupported_numbers=unsupported,
                latency_ms=latency_ms,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=cost,
                judge=scores,
                expected={k: str(facts[q.id][k]) for k in q.checks},
                error=error,
            )
        )
        status = "ok" if (numeric_ok is not False and refusal_ok and tool_ok) else "FAIL"
        logger.info("[%d/%d] %s %s (%d ms)", i, len(questions), q.id, status, latency_ms)
    return results


def write_report(
    results: list[QuestionResult], summary: Summary, meta: dict[str, Any], out_dir: Path
) -> tuple[Path, Path]:
    """Write <timestamp>.md (for people) and <timestamp>.json (for comparing runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    json_path, md_path = out_dir / f"{stamp}.json", out_dir / f"{stamp}.md"
    payload = {"meta": meta, "summary": asdict(summary), "results": [asdict(r) for r in results]}
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    md_path.write_text(render_markdown(results, summary, meta))
    return md_path, json_path


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def summary_table(summary: Summary) -> str:
    """The headline metrics as a markdown table (also printed to the terminal)."""
    judge = "n/a" if summary.mean_judge_score is None else f"{summary.mean_judge_score:.2f} / 5"
    cost = "n/a" if summary.cost_usd is None else f"${summary.cost_usd:.4f}"
    rows = [
        ("Numeric accuracy (A–E)", _pct(summary.numeric_accuracy), f"≥ {MIN_NUMERIC_ACCURACY:.0%}"),
        ("Refusal accuracy (F–G)", _pct(summary.refusal_accuracy), f"≥ {MIN_REFUSAL_ACCURACY:.0%}"),
        ("Over-refusal (on-topic refused)", _pct(summary.over_refusal_rate), "0%"),
        ("Tool selection", _pct(summary.tool_accuracy), ""),
        ("Mean judge score", judge, "≥ 4.0"),
        ("Median latency", f"{summary.median_latency_ms / 1000:.1f} s", "< 6 s"),
        ("Answers flagged by number guardrail", str(summary.guardrail_flags), "0"),
        ("Tokens in / out", f"{summary.input_tokens} / {summary.output_tokens}", ""),
        ("Estimated cost (agent)", cost, ""),
        ("Errors", str(summary.errors), "0"),
    ]
    lines = ["| Metric | Result | Target |", "|---|---|---|"]
    lines += [f"| {name} | {value} | {target} |" for name, value, target in rows]
    return "\n".join(lines)


def render_markdown(results: list[QuestionResult], summary: Summary, meta: dict[str, Any]) -> str:
    """The human-readable report."""
    gate = "PASSED" if summary.gate_passed else "FAILED: " + "; ".join(summary.gate_reasons)
    lines = [
        f"# Eval report — {meta['suite']} — {meta['started_at']}",
        "",
        f"Model `{meta['model']}`, judge `{meta['judge_model']}`, frozen clock "
        f"`{meta['eval_now']}`, fixture {meta['fixture']}. **Gate: {gate}**",
        "",
        summary_table(summary),
        "",
        "## Per question",
        "",
        "| id | expect | tools | numbers | refusal | judge | ms | failed checks / guardrail |",
        "|---|---|---|---|---|---|---|---|",
    ]
    mark = {True: "✅", False: "❌", None: "–"}
    for r in results:
        judge = f"{r.judge['overall']:.1f}" if r.judge else "–"
        notes = ", ".join(r.failed_checks)
        if r.unsupported_numbers:
            notes += f" unsupported: {', '.join(r.unsupported_numbers)}"
        if r.error:
            notes += f" ERROR {r.error[:60]}"
        lines.append(
            f"| {r.id} | {r.expect} | {mark[r.tool_correct]} | {mark[r.numeric_correct]} | "
            f"{mark[r.refusal_correct]} | {judge} | {r.latency_ms} | {notes} |"
        )
    failures = [
        r for r in results
        if r.numeric_correct is False or not r.refusal_correct or not r.tool_correct or r.error
    ]  # fmt: skip
    if failures:
        lines += ["", "## Failures in detail", ""]
        for r in failures:
            lines += [
                f"### {r.id}: {r.question}",
                f"- tools used: {', '.join(r.tools_used) or 'none'}",
                f"- expected facts: {r.expected or '–'}",
                f"- answer: {r.answer or '(empty)'}",
                "",
            ]
    return "\n".join(lines) + "\n"


@app.command()
def main(
    suite: Annotated[str, typer.Option(help="Golden file name in evals/golden/")] = "golden",
    limit: Annotated[int | None, typer.Option(help="Only the first N questions")] = None,
    ids: Annotated[str | None, typer.Option(help="Comma-separated question ids")] = None,
    check: Annotated[bool, typer.Option(help="No LLM: validate and print ground truth")] = False,
    agent: Annotated[
        str | None, typer.Option(help="rules (free) or llm (Claude); default: AGENT_MODE")
    ] = None,
    judge: Annotated[
        bool | None,
        typer.Option(help="LLM judge (paid); default: on only if ANTHROPIC_API_KEY is set"),
    ] = None,
    gate: Annotated[bool, typer.Option(help="Exit 1 when below thresholds")] = True,
) -> None:
    """Run the evaluation suite."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2", "anthropic", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    questions = load_suite(suite)
    if ids:
        wanted = set(ids.split(","))
        questions = [q for q in questions if q.id in wanted]
    if limit:
        questions = questions[:limit]
    facts = validate_suite(questions)
    if check:
        for q in questions:
            shown = {k: str(facts[q.id][k]) for k in q.checks}
            typer.echo(f"{q.id:9} {q.expect:13} {shown}")
        typer.echo(f"\n{len(questions)} questions OK")
        return

    settings = get_settings()
    engine = load_eval_database()
    ctx = ToolContext(
        session_factory=lambda: Session(engine),
        area=settings.price_area,
        tz=local_tz(),
        vat_rate=Decimal(str(settings.vat_rate)),
        now=lambda: EVAL_NOW,
    )
    mode = agent or settings.agent_mode
    if mode == "rules":
        model: str | None = RULES_MODEL
        agent_factory: Callable[[], Agent] = lambda: RuleAgent(ctx)  # noqa: E731
    elif mode == "llm":
        model = settings.llm_model
        graph = build_graph(build_llm(settings), build_tools(ctx))
        callbacks = tracing_callbacks(settings)
        agent_factory = lambda: ChatAgent(graph, SessionMemory(), callbacks)  # noqa: E731
    else:
        raise typer.BadParameter("agent must be 'rules' or 'llm'")
    use_judge = judge if judge is not None else settings.anthropic_api_key is not None
    judge_runnable = build_judge(settings) if use_judge else None
    judge_model = (settings.judge_model or settings.llm_model) if use_judge else None

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    results = asyncio.run(
        run_questions(
            questions,
            facts,
            agent_factory,
            judge_runnable,
            model,
            judge_model,
        )
    )
    summary = summarize(results)
    meta = {
        "suite": suite,
        "started_at": started_at,
        "model": model,
        "judge_model": judge_model,
        "eval_now": EVAL_NOW.isoformat(),
        "fixture": f"{FIRST_DAY}..{LAST_DAY}",
        "questions": len(questions),
    }
    md_path, json_path = write_report(results, summary, meta, REPORTS_DIR)
    typer.echo("\n" + summary_table(summary))
    typer.echo(f"\nReport: {md_path}\nJSON:   {json_path}")
    if gate and not summary.gate_passed:
        typer.echo("GATE FAILED: " + "; ".join(summary.gate_reasons), err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
