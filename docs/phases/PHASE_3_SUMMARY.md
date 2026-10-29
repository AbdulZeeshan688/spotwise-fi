# Phase 3 — Data quality: summary

Requirements: DQ-01 … DQ-06, API-04.

## What was built
- `src/spotwise/quality/checks.py`: five **pure** check functions (no database). Each takes a day's rows and returns a `CheckResult(name, day, status, details)`:
  - `check_completeness` (DQ-01): the expected slots come from `zoneinfo`, so a DST day expects 92/100 quarters (or 23/25 hours). Missing and misaligned slots are listed.
  - `check_duplicates` (DQ-02): the same slot twice, or an hourly row for an hour that also has 15-minute rows.
  - `check_spikes` (DQ-03): robust z-score from the **median and MAD** of the previous 30 days. It only ever **warns**.
  - `check_negative_prices` (DQ-05): status `info` with the count and times. Never a failure.
  - `check_staleness` (DQ-04): tomorrow is still incomplete after 15:00 Helsinki time → warn.
- `src/spotwise/quality/report.py`: the runner (the only part that touches the DB). It loads rows, runs the checks, saves everything to `quality_results` with one shared `run_at`, and computes the overall colour.
- `GET /quality/latest` (API-04): `overall` (green/yellow/red/unknown), `run_at` in Helsinki time, the worst status per check, and every result with details.
- CLI: `daily` now runs the checks after ingestion (also after a failed ingestion, because that's when you need them most). New command: `quality --days N` checks history without fetching.

## Decisions (and why)
- **A fourth status, `info`**, next to pass/warn/fail. DQ-05 says negative prices are "recorded as info", and a separate status keeps them visible without making the badge yellow.
- **Colour rule:** any fail → red, any warn → yellow, otherwise green. No runs yet → `unknown`.
- **Which days are checked:** yesterday and today by default. Tomorrow gets the day checks only once it is fully published; before that, only staleness looks at it. Otherwise porssisahko's "first hour of tomorrow" (it arrives before the rest) would make completeness fail every morning.
- **Spike threshold 5** (not the textbook 3.5). Spot prices have heavy tails, so 3.5 would warn almost daily. It's a constant at the top of `checks.py` and easy to tune.
- **Publication deadline 15:00 Helsinki.** Prices normally appear around 14:00, so this allows an hour of slack before warning.
- **No pandas.** `statistics.median` is enough for median/MAD, so no new dependency was needed.
- **`Annotated[..., Depends(...)]`** in the API routes: FastAPI's recommended style, and it satisfies ruff's B008 rule.

## Verified
- ruff, mypy: clean. **89 tests pass** against a real Postgres 16. They cover DST days in both eras, a gap, a misaligned slot, a duplicate, an hourly/quarter overlap, a spike, "one huge spike doesn't hide the next", negative prices, staleness before and after the deadline, a partly published tomorrow, the runner, and the API.
- By hand, with real porssisahko data: `daily` → 9 results, green. Deleted one row (2026-10-28 10:00) → `quality` → completeness **fail**, overall **red**, `/quality/latest` lists `"missing": ["2026-10-28T10:00+02:00"]`.

## Learn this (interview)
- **Why data-quality checks:** the agent's answers are only as good as the data. Checks catch gaps, duplicates and late data *before* a user gets a wrong answer, and the badge makes data health visible.
- **Why median/MAD, not mean/std:** one extreme value pulls the mean and inflates the std, so the outlier partly hides itself (masking). The median and MAD hardly move, so outliers stay visible. Test: `test_one_huge_spike_in_history_does_not_hide_the_next_one`.
- **Pure checks + separate runner:** the checks can be tested with plain lists in milliseconds. Only the runner needs a database.
