# CLAUDE.md — SpotWise FI

Project rules for Claude Code. Read this before every task. The full spec is in `docs/PROJECT_BRIEF.md`.

## What we're building
A Finnish electricity spot-price assistant: daily price ingestion → PostgreSQL → data-quality checks → typed price tools → LangGraph agent → evaluation harness → React/TypeScript web app.

## Who I am
Junior developer (Python strong, JavaScript/React basic, TypeScript new). Keep code simple and readable over clever. When you make a non-obvious decision, add a short comment or note why in the phase SUMMARY.

## Stack (do not change without asking)
- Python 3.12, managed with **uv** (`uv add`, `uv run`). No pip/poetry.
- FastAPI, Pydantic v2, SQLAlchemy 2.x (typed, `Mapped[...]`), Alembic, httpx, pandas (quality checks only).
- PostgreSQL 16 (Docker Compose locally).
- Agent: LangGraph + `langchain-anthropic`. Model name comes from env (`LLM_MODEL`), never hardcoded.
- Tracing: Langfuse (Python SDK), enabled only when keys are set.
- Tests: pytest, pytest-asyncio, hypothesis (for price math), respx (mock HTTP).
- Lint/format: ruff (lint + format), mypy in strict-ish mode for `src/`.
- Frontend (`web/`): Vite + React + TypeScript (strict), Recharts, Vitest + Testing Library.
- CI: GitHub Actions.

## Repo layout
```
src/spotwise/
  config.py            # pydantic-settings, reads .env
  db/                  # models.py, session.py, alembic migrations in /migrations
  ingest/              # sources/ (entsoe.py, porssisahko.py), pipeline.py, cli.py
  quality/             # checks.py, report.py
  prices/              # pure price math: windows.py, stats.py, units.py (NO database or LLM here)
  tools/               # thin agent tools that call prices/ + db
  agent/               # graph.py, prompts.py, guardrails.py
  api/                 # FastAPI app: routes/health.py, prices.py, quality.py, chat.py
evals/                 # golden/*.yaml, fixtures/, runner.py, metrics.py, judge.py, reports/
tests/                 # mirrors src/ structure
web/                   # Vite React TS app
.github/workflows/     # ci.yml, ingest.yml (daily cron), evals.yml (manual)
```

## Domain rules (important, easy to get wrong)
- **Time:** store all timestamps as UTC `timestamptz`. Convert to `Europe/Helsinki` only at the edges (API responses, agent answers, UI). Use `zoneinfo`, never fixed offsets.
- **DST:** days can have 23 or 25 hours. Never assume 24 hours or 96 quarters per day; compute expected slot counts from the timezone.
- **Resolution:** the Nordic day-ahead market uses **15-minute** prices since autumn 2025; older data is **hourly**. Store each price with its `resolution_minutes` (15 or 60). Hourly views are averages of quarters.
- **Units:** sources give €/MWh. `c/kWh = €/MWh / 10`. Consumer price incl. VAT: multiply by `1 + VAT_RATE` (VAT_RATE from config, default 0.255 for Finland). Always label which one you show.
- **Negative prices happen in Finland.** They are valid data, not errors.
- **Publication time:** next-day prices appear in the early afternoon Finnish time. Before that, "tomorrow" has no data; the agent must say so, not guess.

## Agent rules
- The LLM never invents numbers. Every price, time or statistic in an answer must come from a tool call in that turn.
- Tools are typed functions with Pydantic input/output. No free-form SQL tool.
- Off-topic questions → polite refusal with a one-line description of what SpotWise can do.
- Answers state the time range and whether prices include VAT.

## Code style
- Type hints everywhere. Small functions. Docstrings on public functions (one or two lines).
- No `print` in app code; use `logging` (structured, JSON in production).
- Config only via `spotwise.config.Settings`. No `os.getenv` scattered around.
- Database writes are **idempotent** (upsert on `(area, ts_start, resolution_minutes)`).
- Errors from external APIs: retry with backoff (max 3), then fail loudly with a clear log line.

## Testing rules
- Every new function in `prices/`, `quality/` and `ingest/` gets unit tests. Mock HTTP with respx; never call real APIs in unit tests.
- Agent tests use a fake/stub LLM where possible. Real-LLM tests live only in `evals/`.
- **Never delete or weaken a test to make it pass.** If a test is wrong, explain why and ask.
- `uv run pytest` and `uv run ruff check .` must pass before a phase is marked done.

## Commands
```bash
docker compose up -d db                 # start Postgres
uv run alembic upgrade head             # migrate
uv run python -m spotwise.ingest.cli backfill --days 730
uv run python -m spotwise.ingest.cli daily
uv run uvicorn spotwise.api.main:app --reload
uv run pytest
uv run python -m evals.runner --suite golden
cd web && npm run dev / npm test
```

## Never
- Never commit `.env`, API keys or tokens. Never print secrets in logs.
- Never add a dependency without saying why in one line.
- Never change the stack or the folder layout without asking.
- Never run destructive DB commands (drop, truncate) outside tests.
