"""Ingestion pipeline: fetch → normalise → upsert, logged in `ingestion_runs`."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from spotwise.config import Settings
from spotwise.db.models import IngestionRun, Price
from spotwise.ingest.normalise import normalise_slots
from spotwise.ingest.sources.base import PriceSlot, Source, SourceError
from spotwise.ingest.sources.entsoe import EntsoeSource
from spotwise.ingest.sources.porssisahko import PorssisahkoSource
from spotwise.timeutils import local_day_bounds_utc

logger = logging.getLogger(__name__)

# One request per month keeps responses small; ENTSO-E allows up to a year.
CHUNK_DAYS = 31
UPSERT_BATCH_SIZE = 1000


@dataclass
class RunResult:
    """Outcome of one pipeline run."""

    run_id: int
    status: str  # 'success' | 'partial' | 'failed'
    rows_upserted: int
    sources_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build_sources(settings: Settings, client: httpx.Client) -> list[Source]:
    """ENTSO-E first with porssisahko as fallback, or porssisahko alone without a token."""
    fallback = PorssisahkoSource(client)
    if settings.entsoe_token is None:
        logger.info("ENTSOE_TOKEN not set, using porssisahko.net only")
        return [fallback]
    token = settings.entsoe_token.get_secret_value()
    return [EntsoeSource(token, settings.price_area, client), fallback]


def day_chunks(
    date_from: date, date_to: date, chunk_days: int = CHUNK_DAYS
) -> list[tuple[date, date]]:
    """Split an inclusive day range into inclusive chunks of at most `chunk_days` days."""
    chunks = []
    chunk_start = date_from
    while chunk_start <= date_to:
        chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), date_to)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def upsert_prices(session: Session, slots: Sequence[PriceSlot], area: str, source: str) -> int:
    """Insert or update slots; return how many rows were actually written.

    Unchanged rows are skipped, so re-running the same range returns 0. Data from
    ENTSO-E (exact) is never overwritten by porssisahko (rounded, converted).
    """
    written = 0
    for i in range(0, len(slots), UPSERT_BATCH_SIZE):
        batch = slots[i : i + UPSERT_BATCH_SIZE]
        new = insert(Price).values(
            [
                {
                    "area": area,
                    "ts_start": slot.ts_start,
                    "resolution_minutes": slot.resolution_minutes,
                    "price_eur_mwh": slot.price_eur_mwh,
                    "source": source,
                }
                for slot in batch
            ]
        )
        upsert = new.on_conflict_do_update(
            constraint="uq_prices_slot",
            set_={
                "price_eur_mwh": new.excluded.price_eur_mwh,
                "source": new.excluded.source,
                "fetched_at": func.now(),
            },
            where=or_(
                Price.price_eur_mwh.is_distinct_from(new.excluded.price_eur_mwh),
                Price.source.is_distinct_from(new.excluded.source),
            )
            & ~((Price.source == "entsoe") & (new.excluded.source == "porssisahko")),
        ).returning(Price.id)
        # RETURNING gives one row per inserted or changed slot
        written += len(session.execute(upsert).all())
    return written


def run_ingestion(
    session: Session,
    sources: Sequence[Source],
    date_from: date,
    date_to: date,
    area: str,
    tz: ZoneInfo,
) -> RunResult:
    """Ingest Helsinki-local days date_from..date_to (inclusive), chunk by chunk.

    Each chunk tries the sources in order and is committed on its own, so a failure
    halfway through a long backfill keeps what was already saved.
    """
    run = IngestionRun(
        started_at=datetime.now(UTC),
        source=sources[0].name,
        date_from=date_from,
        date_to=date_to,
        status="running",
    )
    session.add(run)
    session.commit()

    result = RunResult(run_id=run.id, status="running", rows_upserted=0)
    chunks = day_chunks(date_from, date_to)
    failed_chunks = 0
    try:
        for chunk_from, chunk_to in chunks:
            written = _ingest_chunk(session, sources, chunk_from, chunk_to, area, tz, result)
            if written is None:
                failed_chunks += 1
            else:
                result.rows_upserted += written
    except Exception as exc:
        # Unexpected (e.g. database) error: record it, then fail loudly.
        session.rollback()
        result.errors.append(f"unexpected error: {exc!r}")
        _finish_run(session, run, result, "failed")
        logger.exception("Ingestion run %d crashed", run.id)
        raise

    if failed_chunks == len(chunks):
        status = "failed"
    elif failed_chunks:
        status = "partial"
    else:
        status = "success"
    _finish_run(session, run, result, status)
    return result


def _ingest_chunk(
    session: Session,
    sources: Sequence[Source],
    chunk_from: date,
    chunk_to: date,
    area: str,
    tz: ZoneInfo,
    result: RunResult,
) -> int | None:
    """Fetch and save one chunk. Returns rows written, or None if every source failed."""
    start, _ = local_day_bounds_utc(chunk_from, tz)
    _, end = local_day_bounds_utc(chunk_to, tz)
    for source in sources:
        try:
            slots = normalise_slots(source.fetch(start, end), start, end)
        except SourceError as exc:
            result.errors.append(f"{chunk_from}..{chunk_to}: {exc}")
            logger.warning("%s failed for %s..%s: %s", source.name, chunk_from, chunk_to, exc)
            continue
        written = upsert_prices(session, slots, area, source.name)
        session.commit()
        if source.name not in result.sources_used:
            result.sources_used.append(source.name)
        logger.info(
            "%s..%s: %d slots from %s, %d rows written",
            chunk_from,
            chunk_to,
            len(slots),
            source.name,
            written,
        )
        return written
    logger.error("All sources failed for %s..%s", chunk_from, chunk_to)
    return None


def _finish_run(session: Session, run: IngestionRun, result: RunResult, status: str) -> None:
    result.status = status
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.rows_upserted = result.rows_upserted
    run.source = ",".join(result.sources_used) or run.source
    run.error = "\n".join(result.errors)[:4000] or None
    session.commit()
    logger.info(
        "Ingestion run %d %s: %d rows written, sources=%s",
        run.id,
        status,
        result.rows_upserted,
        run.source,
    )
