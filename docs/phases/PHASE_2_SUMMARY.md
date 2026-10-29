# Phase 2 — Ingestion pipeline: summary

Requirements: DATA-01 … DATA-07.

## What was built
- `src/spotwise/timeutils.py`: Helsinki-day ↔ UTC helpers, DST-aware expected slot counts, and the 15-minute switch date (2025-10-01).
- `ingest/sources/base.py`: `PriceSlot`, the `Source` interface, `SourceError`, and `get_with_retry` (backoff 1 s/2 s/4 s, max 3 retries, never logs the URL because it may contain the token).
- `ingest/sources/entsoe.py`: A44 XML parser. It reads the resolution from each Period and fills A03 omitted positions, and treats "No matching data" as empty, not as an error.
- `ingest/sources/porssisahko.py`: the free fallback. It converts c/kWh incl. VAT → €/MWh excl. VAT.
- `ingest/normalise.py`: converts to UTC, keeps the requested range, removes duplicates, and drops an hourly slot when 15-minute slots exist for that hour.
- `ingest/pipeline.py`: chunked fetch (31 days), source fallback, idempotent upsert, and an `ingestion_runs` log.
- `ingest/cli.py`: `backfill --days N` and `daily` (typer). Exit code 1 if a run isn't fully successful.
- `.github/workflows/ingest.yml`: daily cron at 12:30 and 14:30 UTC, plus a manual run.

## What the API research found (2026-10-29)
- **porssisahko.net** gives **c/kWh INCLUDING VAT**, not €/MWh. VAT history: 24%, then 10% (1.12.2022–30.4.2023), then 24%, then 25.5% from 1.9.2024. **Negative prices have 0% VAT.** It has no date-range endpoint (only `latest-prices.json`, about 48 h, and `price.json?date=` for a single moment), and a limit of 30 requests per 10 s.
- **The 15-minute switch** is visible in the data: 2025-09-30 22:00 UTC (= 2025-10-01 00:00 Helsinki) is the first slot whose quarters have different prices.
- **ENTSO-E**: `https://web-api.tp.entsoe.eu/api`, `documentType=A44`, `in_Domain=out_Domain=10YFI-1--------U`, `contract_MarketAgreement.type=A01`, `periodStart/End` as UTC `yyyyMMddHHmm`, at most 1 year per request. "No data" comes back as an `Acknowledgement_MarketDocument`, sometimes with HTTP 200 and sometimes 400.

## Decisions (and why)
- **We store €/MWh excl. VAT for both sources.** porssisahko values are converted back, which is accurate to about 0.01 €/MWh because they round to 0.001 c/kWh incl. VAT.
- **porssisahko never overwrites ENTSO-E rows** (a rule in the upsert). ENTSO-E is the exact, official value.
- **The upsert only touches changed rows** (`ON CONFLICT … DO UPDATE … WHERE value changed`, plus `RETURNING`). That's how a re-run reports **0 rows written**.
- **Each 31-day chunk is committed on its own**, so a crash on month 20 of a backfill keeps months 1–19. A run is `partial` if some chunks failed and `failed` if all did.
- **A run row is created as `running` first and updated at the end**, so a run that crashed is still visible in `ingestion_runs`.
- **Backfill without an ENTSO-E token is slow.** porssisahko needs one request per slot (about 2.5/s), so 30 days ≈ 20 min and 730 days ≈ 6 h. Get the ENTSO-E token for the full backfill.
- **XML is parsed with `defusedxml`**, because it's data from the internet. Tag namespaces are ignored because ENTSO-E changes the namespace version.
- **DB tests run inside a transaction that is rolled back**, so `pytest` never leaves rows in your local database.
- **The ingest workflow skips with a warning if the `DATABASE_URL` secret isn't set.** The production DB arrives in Phase 8.

## Known gap
- **The ENTSO-E test fixtures are synthetic** (built by hand from the documented format), because there's no token yet. When the token arrives, save one real A44 response (without the token!) in `tests/fixtures/` and add a parser test for it.

## Verified
- ruff, mypy: clean. 59 tests pass against a real Postgres 16 (DST 23/25-hour and 92/100-quarter days, A03 gaps, negative prices, retries, fallback, idempotency, partial runs).
- Live run against porssisahko.net: `daily` → 100 rows; `daily` again → 0 rows; `backfill --days 1` → +96 rows. A stored value was checked by hand: 2.376 c/kWh incl. VAT → 18.932 €/MWh.

## Learn this (interview)
- **Idempotency / upsert**: `INSERT … ON CONFLICT (area, ts_start, resolution_minutes) DO UPDATE`. Running the job twice gives the same database, so cron retries are safe.
- **Why UTC in the DB**: one unambiguous timeline. In local time, 03:00–04:00 on the last Sunday of October happens twice.
- **How DST breaks naive code**: "a day = 24 hours = 96 quarters" is wrong twice a year (92 and 100 quarters). We compute the day length from `zoneinfo`.
