# Phase 4 — Price tools: summary

Requirements: PRICE-01 … PRICE-07, API-02, API-03.

## What was built
`src/spotwise/prices/` is **pure math**: no database, no LLM, no HTTP.
- `slot.py`: `PriceSlot` (moved here from ingestion, because price math shouldn't depend on ingestion code) plus helpers. These split slots into equal steps (an hourly slot becomes 4 equal quarters when needed), split a series at gaps (`contiguous_runs`), and cut it to a range (`clip`).
- `units.py` (PRICE-01): €/MWh → c/kWh, and VAT. **The only place VAT is applied.**
- `windows.py` (PRICE-02/03): `cheapest_window` / `most_expensive_window` with a sliding window.
- `stats.py` (PRICE-04/05/06): `price_stats`, `compare_periods`, `estimate_cost`, `hourly_averages`.

Other files:
- `db/queries.py`: `load_slots`, the one shared read query (used by quality, the API, and the Phase 5 agent tools).
- `GET /prices?from=&to=&resolution=15|60&vat=true|false` (API-02). Defaults to today + tomorrow, in c/kWh incl. VAT, with times in Helsinki time.
- `GET /prices/cheapest-window?date=&hours=&vat=` (API-03).

## Decisions (and why)
- **Decimal for all money math**, not float. With float, `0.1 + 0.2 != 0.3`, and sums of hundreds of slots drift. Values keep full precision inside `prices/` and are rounded only at the edge (3 decimals in the API).
- **No VAT on negative prices.** In Finland, a credit to the customer isn't taxed, and porssisahko.net applies 0% VAT to negative prices too. Because of this, a cost "incl. VAT" is computed per slot, not as "excl. VAT × 1.255".
- **Sliding window with a running sum:** O(n). Add the slot entering the window and subtract the one leaving. All windows have the same length, so comparing sums is the same as comparing averages (and avoids division). Ties go to the earliest window.
- **Windows never cross a gap.** The series is split into contiguous runs first.
- **Step size:** 15 minutes if the range has any 15-minute data, otherwise 60. Mixed data (around 1 Oct 2025) is split into quarters, which is exact because the hourly price was the same for all 4 quarters. The duration must be a multiple of the step.
- **Stats are time-weighted** for mixed data, because they're computed on equal steps.
- **`estimate_cost` refuses** if any part of the range has no price, instead of guessing.
- **`/prices/cheapest-window` treats a future day without all its slots as "not published yet"** (404 with the 14:00 note). porssisahko often has tomorrow's first hour early, and a "cheapest window" from that hour alone would be wrong. For past days with gaps, the response has `data_complete: false`.
- **`resolution` is an `int` checked in code**, because `Literal[15, 60]` rejected the query string `"60"` (bug found while testing).
- **Test isolation fix:** DB tests now start from empty tables *inside* their rolled-back transaction. Before, they silently assumed an empty database and failed once real data existed. Your real data is never touched.

## Verified
- ruff, mypy: clean. **133 tests pass** against Postgres 16, including **hypothesis property tests** (PRICE-07):
  - the cheapest window is ≤ every other gap-free window of the same length (checked against a brute-force oracle), and is a real window from the data;
  - the most expensive window is ≥ every other; cheapest ≤ most expensive; windows stay inside the requested range;
  - an even spread costs mean price × kWh; with only positive prices, the incl. VAT cost is exactly 1.255 × the excl. VAT cost;
  - min ≤ median and mean ≤ max; compare's difference = B − A; VAT never lowers a price.
- Real data check: `/prices/cheapest-window?date=2026-10-29&hours=3` → 02:30–05:30, 0.971 c/kWh incl. VAT. A brute-force check over the `/prices` rows gave the same window and average.

## Learn this (interview)
- **Sliding window:** O(n) instead of O(n·k), by updating a running sum. Gaps split the series first.
- **Property-based testing:** instead of a few hand-picked examples, hypothesis generates hundreds of random series (with gaps, negative prices) and checks *rules* that must always hold. When a rule breaks, it shrinks the input to the smallest failing example.
- **Decimal vs float:** float is binary and can't represent 0.1 exactly, which is fine for statistics but not for money. Decimal is exact for decimal values.
