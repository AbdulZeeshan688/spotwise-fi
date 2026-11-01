# Phase 5 — Agent: summary

> **Update 2026-11-01:** the default agent is now the free rule-based one (`AGENT_MODE=rules`, see `PHASE_6_SUMMARY.md`). Everything below still applies when `AGENT_MODE=llm`.

Requirements: AGENT-01 … AGENT-07, API-05, API-06.

## What was built
- **`tools/periods.py`**: `resolve_period` turns "tomorrow", "last week", "4 weeks ago", "next 8 hours", "today 22:00-06:00", "2026-10-01..2026-10-07" and similar into exact Helsinki start/end times. Pure code, DST-safe.
- **`tools/price_tools.py`**: 9 typed tools with a Pydantic input and output each: `resolve_period`, `get_current_price`, `get_prices`, `find_cheapest_window`, `find_most_expensive_window`, `get_price_stats`, `compare_periods`, `estimate_cost`, `check_data_availability`. They're thin wrappers over `prices/` plus `db/queries.load_slots`, with **no SQL tool**. Every output carries the time range in Helsinki time, `vat_included`/`vat_percent`, and a `coverage` block (expected vs available slots). Missing data comes back as `available: false` with a message (for example "published around 14:00"), not as an exception.
- **`tools/registry.py`**: wraps the tools for LangChain. Bad input (like an unknown period) goes back to the LLM as the tool result, so it can correct itself.
- **`agent/graph.py`**: LangGraph `agent → tools → agent … → END`, with a **limit node** after more than 5 tool calls in one question. The model comes from `LLM_MODEL`.
- **`agent/prompts.py`**: the system prompt. Numbers only from tools in this turn, always `resolve_period` for dates, state the range and VAT, say clearly when data isn't published, and an **exact refusal sentence** for off-topic questions. It contains no example numbers and no date.
- **`agent/guardrails.py`**: `find_unsupported_numbers` checks every number in the answer against this turn's tool outputs and the question (rounding allowed: 1.26 is supported by 1.255).
- **`agent/memory.py`**: per-session memory in RAM. The last 10 messages, plain question/answer text only; the oldest sessions are dropped after 1000.
- **`agent/runner.py`**: `ChatAgent.stream()` (tokens, tool events, and a final `done` with the guardrail result) and `ChatAgent.ask()` (for Phase 6 evals).
- **`agent/tracing.py`**: Langfuse callback, only when both keys are set (AGENT-07).
- **`POST /chat`**: SSE with FastAPI's built-in `EventSourceResponse`. Events: `session`, `token`, `tool`, `done`, `error`. Rate limited per IP (`CHAT_RATE_LIMIT_PER_MIN`, 429 + Retry-After). Returns 503 if the LLM isn't configured. CORS was already limited to `CORS_ORIGINS` (checked: other origins get 400).

## Decisions (and why)
- **No `temperature` (deviation from AGENT-06).** Since API version 2026-10-21, the Claude API returns a 400 for `temperature`/`top_p`/`top_k` on every model, so "temperature 0" is impossible. `LLM_TEMPERATURE` was removed from config. Repeatability comes from the design instead: every number comes from deterministic tools, and evals freeze the clock (`EVAL_NOW`).
- **Dev model `claude-haiku-5-5`** (in `.env.example`): cheap and fast for a tool-calling chat agent. `effort: medium` is set explicitly.
- **Date math is a tool.** LLMs make mistakes with week boundaries, month lengths and DST. `resolve_period` is tested code; the prompt says to always call it.
- **Memory keeps text only, no tool results.** (1) It enforces "numbers from tools in *this* turn". (2) The history we send to Claude is never edited, which newer Claude models require for their thinking blocks.
- **Windows and stats are computed on consumer prices** (`units.to_consumer_slots`). VAT applies only to positive prices, so ranking by raw €/MWh could pick a slightly different "cheapest" window than the one the customer actually pays least for. The `/prices/cheapest-window` endpoint now does the same.
- **The guardrail reports, it doesn't block.** The answer has already streamed when the check runs, so the `done` event carries `unsupported_numbers`, the server logs a warning, and Phase 6 measures it. Blocking would need buffering the whole answer (no streaming) or a second LLM pass.
- **The refusal is one exact sentence**, so evals can check refusals with a string comparison instead of an LLM judge.
- **The rate limiter is in-memory**, fine for one server process. Several instances would need Redis (out of scope).
- **FastAPI's built-in SSE** (`fastapi.sse`) instead of the `sse-starlette` package: no new dependency.
- New dependencies: `langgraph` (agent graph), `langchain-anthropic` (Claude chat model), `langfuse` (tracing). All three are in the CLAUDE.md stack.

## Verified
- ruff, mypy (strict): clean. **195 tests pass** against Postgres 16. The agent tests use a **scripted fake LLM** (`tests/agent/fakes.py`) that streams prepared tool calls and answers, so no real API is called. They cover the tool call → answer flow, the refusal, invented-number detection, tool errors going back to the model, the 5-tool-call limit, memory, SSE event order, input validation, the rate limit (429), and 503 without keys.
- `resolve_period` tests cover DST weeks (169 h), "next 3 hours" across the DST change, month/year boundaries, and errors.
- Tools on real porssisahko data (2026-10-31 00:05): current price 18.824 c/kWh incl. VAT; cheapest 3 h yesterday 00:00–03:00 at 2.278 c/kWh; 40 kWh from 22:00 to 06:00 = 5.11 € excl. / 6.41 € incl. VAT (checked by hand: 40 × 12.773 c = 5.11 €); tomorrow "not published yet, around 14:00".

## Not yet verified (needs your API key)
- **Real Claude answers.** Put `ANTHROPIC_API_KEY` and `LLM_MODEL=claude-haiku-5-5` in `.env`, then test the 7 use cases with the checklist in `docs/PHASE_GUIDE.md`. Phase 6 then measures this systematically.
- **Langfuse traces** (needs the Langfuse keys).

## Learn this (interview)
- **What LangGraph adds over a plain while-loop:** the agent is an explicit graph (nodes and edges), so the tool limit is just another node and route. It gives you streaming of tokens *and* node outputs, callbacks for tracing, and state you can test.
- **Tool calling:** the model doesn't run code. It returns "call `find_cheapest_window` with these JSON args"; we validate the args with Pydantic, run the function, and send the JSON result back. The model only chooses and explains.
- **Why date math lives outside the LLM:** dates have hidden rules (ISO weeks, DST 23/25-hour days, month lengths). Code is tested and deterministic; the LLM is neither.
- **SSE:** one long HTTP response with `text/event-stream`, where the server writes `event:`/`data:` blocks as they happen. It's simpler than WebSockets for one-way streaming and works over a normal POST.
- **Guardrail limits:** the number check catches invented numbers but not wrong *use* of correct numbers, such as citing yesterday's price as today's. That's what the Phase 6 LLM judge is for.
