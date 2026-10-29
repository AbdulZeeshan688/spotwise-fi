"""SQLAlchemy models. Must match the schema in docs/PROJECT_BRIEF.md section 7."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TIMESTAMP


class Base(DeclarativeBase):
    """Base class for all models."""


class Price(Base):
    """One price slot (15 or 60 minutes). `ts_start` is always UTC."""

    __tablename__ = "prices"
    __table_args__ = (
        # Upserts use this key, which makes ingestion idempotent.
        UniqueConstraint("area", "ts_start", "resolution_minutes", name="uq_prices_slot"),
        CheckConstraint("resolution_minutes IN (15, 60)", name="ck_prices_resolution"),
        Index("ix_prices_area_ts_start", "area", "ts_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    area: Mapped[str] = mapped_column(Text, server_default="FI")
    ts_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    resolution_minutes: Mapped[int] = mapped_column(SmallInteger)
    # Can be negative; negative prices are valid data in Finland.
    price_eur_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    source: Mapped[str] = mapped_column(Text)  # 'entsoe' | 'porssisahko'
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class IngestionRun(Base):
    """Audit log entry for one ingestion pipeline run."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    source: Mapped[str] = mapped_column(Text)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    rows_upserted: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)  # 'success' | 'partial' | 'failed'
    error: Mapped[str | None] = mapped_column(Text)


class QualityResult(Base):
    """Result of one data-quality check for one Helsinki-local day."""

    __tablename__ = "quality_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    day: Mapped[date] = mapped_column(Date)
    check_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # 'pass' | 'warn' | 'fail'
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
