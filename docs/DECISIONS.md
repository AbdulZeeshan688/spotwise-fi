# Design decisions

Short notes on the choices that shaped SpotWise FI, and why. Details per phase are in
`docs/phases/`.

## Data
- **UTC in the database, Helsinki time only at the edges.** One unambiguous timeline;
  in local time, one hour of the last Sunday of October happens twice.
- **DST-aware everywhere.** A day has 23, 24 or 25 hours (92/96/100 quarters). Expected
  slot counts come from `zoneinfo`, never from "24".
- **Store each price with its resolution (15 or 60 minutes).** The Nordic market moved
  to 15-minute prices on 1 Oct 2025; history is hourly. Hourly views are averages.
- **€/MWh excluding VAT in storage, for every source.** porssisahko.net returns c/kWh
  *including* the VAT of that day (24%, 10% in winter 2022–23, 25.5% since Sept 2024,
  0% on negative prices), so it is converted back.
- **Idempotent upsert** (`ON CONFLICT … DO UPDATE … WHERE changed`). Re-running ingestion
  writes 0 rows; cron retries are safe. ENTSO-E data (exact) is never overwritten by
  porssisahko data (rounded).

## Data quality
- **Checks are pure functions; a separate runner touches the DB.** Testable in
  milliseconds with plain lists.
- **Spikes use median and MAD, not mean and standard deviation.** One extreme value
  inflates the std and hides itself; the median barely moves.
- **Negative prices are "info", never a failure.** They are real in Finland.

## Price math
- **Decimal for money**, rounded only for display.
- **No VAT on negative prices** (Finnish practice, same as porssisahko.net), so costs
  incl. VAT are computed per 15-minute slot.
- **Windows never cross gaps** and are ranked by the price the consumer pays.
- **Property-based tests (hypothesis)** check rules like "the cheapest window is never
  more expensive than any other window" on hundreds of random series.

## Assistant
- **Math in code, words in the assistant.** Every number comes from a typed tool; there
  is no free-form SQL tool.
- **Date math is a tool (`resolve_period`).** "Last week", "tonight 22–06" and DST are
  resolved by tested code.
- **Rule-based assistant by default, no paid AI.** The project must cost nothing to run.
  A parser maps questions to the same tools the LLM agent uses and answers from
  templates: free, instant and deterministic, and every number comes from a tool by
  construction. The LangGraph + Claude agent is still in the code
  (`AGENT_MODE=llm`) for anyone with an API key.
- **Number guardrail** checks every number in an answer against this turn's tool
  outputs. It caught a real issue in the first eval run (calculated dates).
- **No `temperature`** for the LLM agent: the Claude API rejects sampling parameters
  since 2026-10-21.

## Evaluation
- **Frozen fixture (60 real days) and a frozen clock.** Expected answers never change,
  so a score change always means the assistant changed.
- **Ground truth is computed by `prices/` code, independent of the tools.** A tool bug
  can't move the expected answer; a test proves that removing VAT fails the gate.
- **Deterministic metrics gate the build; the LLM judge is optional.** The judge costs
  money and varies between runs.
- **Evals run on every push in CI**, because the rule agent makes them free.

## Web app and hosting
- **Plain React state, plain CSS, Recharts.** No router or state library for one page.
- **Chart colours were validated** for colour-blindness and contrast in light and dark
  mode; colour is never the only signal (labels, legend, table view).
- **Free hosting split:** Netlify (static site), Render (Docker API), Neon (Postgres),
  GitHub Actions (daily ingest). Render's free tier sleeps when idle, which the web app
  explains to the user instead of looking broken.
- **The Docker image is tested in CI** (build, migrate, start, smoke-test `/health`,
  `/prices`, `/chat`).
