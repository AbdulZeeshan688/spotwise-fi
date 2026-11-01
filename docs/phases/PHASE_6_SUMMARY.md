# Phase 6 — Evaluation harness: summary

Requirements: EVAL-01 … EVAL-07.

## What was built
- **Frozen fixture (EVAL-02)**: `evals/fixtures/prices_fi.csv` holds **real FI prices for 2025-09-17 … 2025-11-15** (60 days), fetched once with `evals/fixtures/build_fixture.py` and committed. It contains hourly days (until 30 Sep), the switch to 15-minute prices (1 Oct), and the 25-hour DST day (26 Oct, 100 quarters). It deliberately has **no data for 16 Nov**, because the frozen clock is `EVAL_NOW = 2025-11-15 10:00` Helsinki, before the next day's publication.
- **Eval database loader**: `evals/fixtures/loader.py` creates the separate `spotwise_eval` database, runs Alembic, replaces its contents with the fixture, and runs the quality checks at `EVAL_NOW`. A safety check refuses any database whose name doesn't end in `_eval` or that equals `DATABASE_URL`.
- **Golden set (EVAL-01)**: `evals/golden/golden.yaml` has all **50 seed questions**, each with `expect` (answer / refusal / not_available), `expected_tools`, a `ground_truth` function and the `checks` (which facts the answer must contain, and their type).
- **Ground truth from code**: `evals/ground_truth.py` computes every expected value from the CSV with the `prices/` functions. It does **not** use the agent's tools or the database, so a bug in a tool can't change the expected answer.
- **Metrics (EVAL-03)**: `evals/metrics.py` records per question: tool selection, numeric correctness (prices ±0.01 c/kWh, € ±0.01, percent ±0.5, times as HH:MM in several spellings, dates in several spellings), refusal correctness, latency, tokens, cost, and number-guardrail flags.
- **LLM judge (EVAL-04, optional, paid)**: `evals/judge.py` with the rubric in `evals/rubric.md`. Scores 1–5 for clarity, states range, states VAT and no invented numbers. It has its own prompt, sees the tool outputs, and uses the API's native JSON-schema structured output.
- **Runner + report (EVAL-05/06)**: `uv run python -m evals.runner --suite golden` writes `evals/reports/<timestamp>.md` (summary table, per-question table, failures in detail) and `.json` (for comparing runs), and **exits 1** if numeric accuracy < 90% or refusal accuracy < 95%. `--check` validates the whole golden set and ground truth without any LLM (free).
- **Manual workflow (EVAL-07)**: `.github/workflows/evals.yml`, `workflow_dispatch` only. It uses a Postgres service, the `ANTHROPIC_API_KEY` secret and `LLM_MODEL`/`JUDGE_MODEL` repository variables (default `claude-haiku-5-5`), and uploads the report as an artifact.

## New agent tools (needed by the seed questions)
- `get_daily_averages`: mean per day plus the cheapest and most expensive day (Q22, Q23). Code picks the extremes, so the LLM doesn't compare numbers.
- `get_price_stats(threshold_c_kwh=…)`: hours above a price (Q25).
- `check_data_availability`: now also returns the first and last date of all stored data (Q38, Q39).
- `get_data_quality`: the latest quality results (Q40).

## Decisions (and why)
- **Fixture end date = the `EVAL_NOW` day.** The seed doc said "about … → 2025-11-18", but with the clock at 15 Nov 10:00, data for 16–18 Nov would make "tomorrow isn't published yet" untestable.
- **Ground truth independent of tools.** Tested: `test_removing_vat_from_the_tools_fails_the_gate` makes the tools drop VAT and checks that numeric accuracy falls to 0% and the gate fails. That's the PHASE_GUIDE "break something on purpose" check, automated and free.
- **Checks look for facts, not exact sentences.** The answer only has to *contain* each expected value (with tolerance). Wording is the judge's job.
- **Refusal accuracy is measured only on F–G questions** (the gate metric). **Over-refusal** (refusing an on-topic question) is reported separately, so an agent that refuses everything can't look good.
- **Three questions are only partly checkable** (noted in the YAML): Q21 weekday vs weekend (no tool, so judge only), Q34 savings (both costs are checked; the subtraction would be LLM arithmetic), Q8 (the window can only come from today's evening; the judge checks that partial data is mentioned).
- **Each question runs in a fresh session**, so earlier answers can't leak into later ones.
- **Cost in USD**, from Anthropic's per-model price table, because that's how the API bills (labelled "estimated").
- **Dependencies:** `pyyaml` (golden set as YAML, as the brief asks; it was already installed by LangChain), `types-pyyaml` (mypy stubs).

## No paid AI: the rule-based agent (decision 2026-11-01)
You decided not to spend money on the project, so there is no Anthropic API key. Instead of switching the chat off, I added a **rule-based agent** and made it the default (`AGENT_MODE=rules`):
- `agent/question.py` parses a question into an intent (current price, window, stats, daily, compare, cost, availability, quality, refuse, no_forecast) plus periods, duration, kWh, VAT and threshold. Pure functions; understands Finnish basics ("Mikä on sähkön hinta nyt?") and shorthand ("cheapest 3h 2day??").
- `agent/rules.py` calls **the same typed tools** as the LLM agent and writes the answer from templates. Every number is copied from a tool result, so the number guardrail passes by construction. It never guesses unpublished prices, and off-topic questions get the same fixed refusal sentence.
- It has the same `stream()` / `ask()` interface as the LLM agent, so `/chat`, the web app and this eval harness didn't change. The Claude/LangGraph agent is still there as `AGENT_MODE=llm`, for anyone with a key.
- **Evals are now free**, so they run on **every push in CI** (`ci.yml`) as a real regression gate, not only by hand. The LLM judge is switched on only when an API key exists.

## Verified
- **Eval run, rule agent, full golden set (50 questions, 60 days of real prices):**

| Metric | Result | Target |
|---|---|---|
| Numeric accuracy (A–E) | 100% | ≥ 90% |
| Refusal accuracy (F–G) | 100% | ≥ 95% |
| Over-refusal (on-topic refused) | 0% | 0% |
| Tool selection | 100% | |
| Answers flagged by number guardrail | 0 | 0 |
| Median latency | < 0.1 s | < 6 s |
| Cost | $0 | |

- **Be honest about the 100%:** the parser rules were written while looking at these 50 questions, so this is "tested on what it was built for". New phrasings will score lower. The next step is a held-out set of rephrased questions that nobody tunes against (ideas in Phase 8).
- The **guardrail found a real problem on the first run** (7 flagged answers): templates printed the last day of a range ("to 2025-11-16"), a date no tool had returned. Fixed by having `resolve_period` return an inclusive `last_day`, so dates also come from tools.
- **A real bug the loader test found:** Alembic's config parser crashed on `%` in a database URL (URL-encoded sockets, or passwords with special characters, which Neon can generate). `migrations/env.py` now escapes it.
- `test_removing_vat_from_the_tools_fails_the_gate` proves the gate catches a tool bug (accuracy drops to 0% and the gate fails), free and in CI.
- **283 backend tests** pass against Postgres 16; ruff and mypy are clean.

## Learn this (interview)
- **Why a frozen fixture and a frozen clock:** the expected answers must never change between runs. Otherwise a drop in accuracy could mean "the agent got worse" *or* "the data changed", and you couldn't tell which.
- **Tool correctness vs answer correctness:** an agent can call the right tool and still misquote the result, or quote correct numbers from the wrong period. We measure both, plus the number guardrail.
- **LLM-as-judge, strengths and weaknesses:** it scores things code can't (clarity, whether partial data was mentioned), but it is itself an LLM. It can be lenient, it varies between runs, and it costs money. So the **gate uses only deterministic metrics**; the judge score is reported, not gated.
- **Regression gate:** CI-style pass/fail on accuracy thresholds. Every bug you fix becomes a new golden question, so it can't come back unnoticed.
