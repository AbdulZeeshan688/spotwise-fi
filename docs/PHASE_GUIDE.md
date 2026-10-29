# Phase Guide — what to say, what to check

For every phase you get:
- **Discuss text:** paste it after `/gsd:discuss-phase N`.
- **Watch out for:** things to look for when you read the PLAN.
- **You test it:** your own checklist for `/gsd:verify-work N`.
- **Learn this:** what you should be able to explain in an interview afterwards.

If a GSD command asks something not covered here, answer from `docs/PROJECT_BRIEF.md`, or say "use the simplest option that meets the requirement".

---

## Phase 1 — Foundation

**Discuss text**
> Phase 1 covers OPS-01, OPS-02 and API-01. Set up the repo exactly as the layout in CLAUDE.md: uv project with Python 3.12, src/spotwise package, FastAPI app with GET /health that also checks the DB connection, pydantic-settings config reading .env, SQLAlchemy 2 models for prices, ingestion_runs and quality_results as in the brief, first Alembic migration, docker-compose.yml with Postgres 16 and a named volume, ruff + mypy config in pyproject.toml, and .github/workflows/ci.yml running ruff, mypy and pytest against a Postgres service container. Add a Makefile or justfile with the common commands. Keep it minimal. No ingestion code yet.

**Watch out for**
- It shouldn't add extra frameworks (no Celery, no Redis).
- The migration must match the brief's schema (the UNIQUE constraint on area, ts_start, resolution_minutes).

**You test it**
- [ ] `docker compose up -d db` starts Postgres.
- [ ] `uv run alembic upgrade head` creates 3 tables (check with `docker compose exec db psql -U postgres -c '\dt'`).
- [ ] `uv run uvicorn spotwise.api.main:app --reload`, then open http://localhost:8000/health → shows ok and the DB is reachable.
- [ ] `uv run pytest` passes. Push to GitHub and the CI is green.

**Learn this:** what Alembic does, why `pydantic-settings`, what the Postgres service container in CI is for.

---

## Phase 2 — Ingestion pipeline

**Discuss text**
> Phase 2 covers DATA-01 to DATA-07. First research the CURRENT API docs for ENTSO-E (day-ahead prices, documentType A44, domain 10YFI-1--------U) and porssisahko.net. The market moved to 15-minute prices in autumn 2025, so check the formats; don't rely on memory. Save one real sample response from each source into tests/fixtures/ (anonymised; no tokens in files) and write parser tests against them. Build a Source interface with two implementations, a normaliser that outputs (ts_start UTC, resolution_minutes, price_eur_mwh), and an idempotent upsert. Handle DST days and ENTSO-E's omitted repeated positions (curve A03). CLI with typer: `backfill --days N` and `daily`. Log runs to ingestion_runs. Add .github/workflows/ingest.yml with a daily cron in the early afternoon Finnish time plus a retry 2 hours later, using GitHub secrets for DATABASE_URL and ENTSOE_TOKEN. If ENTSOE_TOKEN is empty, fall back to porssisahko automatically.

**Watch out for**
- Parsing must read the `resolution` from the data, not assume 60 or 15.
- Backfill should fetch in chunks (for example 1 month per request) with backoff, not 730 separate calls at once.
- No real API calls in unit tests (respx mocks).

**You test it**
- [ ] `uv run python -m spotwise.ingest.cli backfill --days 30` → rows in the DB.
- [ ] Run it again → 0 new rows (idempotent).
- [ ] Check a DST day in SQL: `SELECT count(*) FROM prices WHERE ts_start >= '2026-03-29 00:00+02' AND ts_start < '2026-03-30 00:00+03';` gives 23 hourly slots or 92 quarter slots, not 24 or 96.
- [ ] `ingestion_runs` has a success row.
- [ ] Trigger the ingest workflow manually on GitHub ("Run workflow") and it succeeds.

**Learn this:** idempotency, upsert (`ON CONFLICT`), why UTC in the DB, how DST breaks naive code.

---

## Phase 3 — Data quality

**Discuss text**
> Phase 3 covers DQ-01 to DQ-06 and API-04. Write each check as a small pure function that takes a day's rows and returns a CheckResult (name, status pass/warn/fail, details dict). Completeness must compute expected slots per Helsinki-local day from zoneinfo (handles 23/25-hour days). Spikes: robust method (median and MAD over the last 30 days), warn only. Negative prices: info, never fail. Staleness: tomorrow missing after the expected publication time → warn. Run checks automatically at the end of `daily` and save to quality_results. Add GET /quality/latest returning the latest status per check and an overall colour (green/yellow/red). Tests for every check, including DST days, a day with a gap, a day with a duplicate, a spike and negative prices.

**Watch out for**
- Checks shouldn't query the DB inside the pure functions (keep DB access in a separate runner).

**You test it**
- [ ] Run `daily` and confirm the `quality_results` rows appear.
- [ ] Delete one price row by hand → the completeness check fails for that day.
- [ ] `/quality/latest` returns JSON with a colour.

**Learn this:** why data quality checks matter, why median/MAD rather than mean/std for spikes.

---

## Phase 4 — Price tools

**Discuss text**
> Phase 4 covers PRICE-01 to PRICE-07 and API-02, API-03. Put all math in src/spotwise/prices/ as pure functions working on a list or Series of (ts_start, resolution, price) with no DB or LLM imports. Cheapest/most-expensive window: sliding window over 15-minute steps, durations given in minutes and must be a multiple of the resolution; if hourly data only, use hourly steps. Use Decimal or careful float rounding for money, and document which. Stats, compare_periods and estimate_cost as in the brief. Property-based tests with hypothesis (e.g. the cheapest window ≤ every other window of the same length; the cost of an even spread equals the mean price × kWh). Then add GET /prices and GET /prices/cheapest-window endpoints using these functions, with Pydantic response models.

**Watch out for**
- Window logic must handle ranges with gaps (it shouldn't silently join non-contiguous slots).
- VAT conversion is in one place only (`units.py`).

**You test it**
- [ ] http://localhost:8000/prices?from=…&to=… returns prices in c/kWh incl. VAT.
- [ ] `/prices/cheapest-window?date=<tomorrow>&hours=3` gives a sensible night-time window most days.
- [ ] Check one answer by hand in a spreadsheet: same window, same average.

**Learn this:** sliding-window algorithm, property-based testing, Decimal vs float.

---

## Phase 5 — Agent

**Discuss text**
> Phase 5 covers AGENT-01 to AGENT-07, API-05 and API-06. Build a LangGraph graph (agent node + ToolNode, max 5 tool calls) using langchain-anthropic with the model from LLM_MODEL. Tools in src/spotwise/tools/ are thin typed wrappers over prices/ functions plus DB reads: get_current_price, get_prices, find_cheapest_window, find_most_expensive_window, get_price_stats, compare_periods, estimate_cost, check_data_availability. Relative dates are resolved by a deterministic helper (resolve_period("tomorrow"|"this week"|"last month"|explicit dates) in Europe/Helsinki) that is itself a tool, so the LLM never does date math. System prompt in prompts.py: answer only about Finnish electricity prices, numbers only from tool results, always state range and VAT, say clearly when tomorrow isn't published. POST /chat streams tokens via SSE and keeps short per-session memory in RAM (last 10 messages). Add Langfuse callback when keys exist. Unit tests with a fake LLM that emits scripted tool calls; no real API in unit tests. Simple rate limit on /chat.

**Watch out for**
- No "run any SQL" tool.
- The system prompt shouldn't contain example numbers that the model could copy.

**You test it** (with `curl` or the FastAPI docs page at /docs)
- [ ] Ask all 7 use cases from the brief and check each number against `/prices` or your own SQL.
- [ ] Ask "Who won the football match yesterday?" → polite refusal.
- [ ] Ask about tomorrow before ~14:00 Finnish time → it says prices aren't published yet.
- [ ] Open Langfuse and see the trace with tool calls.

**Learn this:** what LangGraph adds over a plain loop, what tool calling is, why date math lives outside the LLM, how SSE streaming works.

---

## Phase 6 — Evaluation harness

**Discuss text**
> Phase 6 covers EVAL-01 to EVAL-07. Create evals/fixtures/ with a frozen 60-day price snapshot (include the last Sunday of October 2025 DST day and some negative prices; export it from the real DB once and commit the CSV) and a loader that creates a separate eval database. Freeze "now" for evals with an injectable clock (e.g. EVAL_NOW=2025-11-15T10:00:00+02:00) so relative dates are deterministic. Convert docs/EVAL_SEED_QUESTIONS.md into evals/golden/*.yaml (id, question, category, expected_tools, ground_truth computed by calling the prices/ functions on the fixture, tolerance). Runner: runs each question through the real agent at temperature 0, records tool calls, extracts numbers from the answer, compares to ground truth, measures latency and tokens. LLM-as-judge (judge.py) scores clarity, states range, states VAT, no invented numbers on a 1–5 rubric written in evals/rubric.md. Outputs evals/reports/<timestamp>.md + .json and prints a summary table. Gate: exit code 1 if numeric accuracy < 0.90 or refusal accuracy < 0.95. .github/workflows/evals.yml runs on workflow_dispatch only, using secrets.

**Watch out for**
- Ground truth must come from code (the prices/ functions on the fixture), never from the LLM.
- The judge should use a different prompt from the agent and see the tool outputs, so it can check for invented numbers.

**You test it**
- [ ] `uv run python -m evals.runner --suite golden` finishes and writes a report.
- [ ] Break something on purpose (e.g. remove VAT from one tool) → accuracy drops and the gate fails. Then undo it.
- [ ] Run the GitHub workflow manually once.

**Learn this:** why deterministic fixtures, the difference between tool-correctness and answer-correctness, the strengths and weaknesses of LLM-as-judge, regression gates.

---

## Phase 7 — Web app

**Discuss text**
> Phase 7 covers UI-01 to UI-05. In web/, create a Vite + React + TypeScript (strict) app. Typed API client generated from or matching the FastAPI OpenAPI schema. Layout: header with the data-quality badge; main area with a Recharts bar chart of today + tomorrow (15-min bars, hourly toggle, VAT toggle, current slot highlighted, cheapest 3-hour window shaded); side or bottom chat panel with streaming answers (EventSource/fetch stream) and 4 example-question chips. Mobile-first CSS (plain CSS modules or Tailwind; pick one and keep it simple), keyboard accessible, prefers-color-scheme dark support. Vitest + Testing Library tests for the chart data transform, the API client and the chat component. VITE_API_URL from env.

**Watch out for**
- Timezone: show Helsinki time in the UI even if your laptop is in another zone.
- Don't put any API keys in the frontend.

**You test it**
- [ ] `npm run dev` shows the chart with real data.
- [ ] The chat streams an answer word by word.
- [ ] Narrow the browser to phone width → still usable.
- [ ] `npm test` and `npm run build` pass.

**Learn this:** React state for streaming, typed API clients, how you handled timezones in the browser.

---

## Phase 8 — Deploy & polish

**Discuss text**
> Phase 8 covers OPS-03, OPS-04, DOC-01, DOC-02. Deploy the API to Render (or Fly.io) with a Dockerfile, a managed Postgres on Neon (or Supabase) free tier, run migrations on deploy, and point the GitHub ingest workflow at the production DB. Deploy web/ to Netlify with VITE_API_URL. Lock CORS to the Netlify domain. Write the README per DOC-01 (pitch, demo link, GIF placeholder, mermaid architecture diagram from the brief, local setup, eval results table copied from the latest report, design decisions, limitations, next steps) and docs/DECISIONS.md. Add a short "Cost & limits" section.

**You test it**
- [ ] The demo URL works on your phone.
- [ ] The next day, the scheduled ingestion has added tomorrow's prices to production.
- [ ] A friend can follow the README and run it locally.
- [ ] Record a 20–30 second GIF (on Mac: Cmd+Shift+5 to record, then convert to GIF with ezgif.com) and add it to the README.

Then run `/gsd:audit-milestone` and `/gsd:complete-milestone`, and see `docs/CV_AND_LINKEDIN.md`.
