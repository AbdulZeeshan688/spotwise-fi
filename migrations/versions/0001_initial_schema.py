"""Initial schema: prices, ingestion_runs, quality_results, prices_hourly view.

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Hourly averages. Where 15-minute data exists for an hour, average the quarters;
# otherwise use the hourly row. Hours are truncated in UTC (Helsinki is a whole-hour
# offset, so UTC hours line up with local hours).
PRICES_HOURLY_VIEW = """
CREATE VIEW prices_hourly AS
SELECT
    p.area,
    date_trunc('hour', p.ts_start, 'UTC') AS ts_start,
    avg(p.price_eur_mwh)                  AS price_eur_mwh,
    count(*)                              AS slot_count
FROM prices p
WHERE p.resolution_minutes = 15
   OR NOT EXISTS (
        SELECT 1 FROM prices q
        WHERE q.area = p.area
          AND q.resolution_minutes = 15
          AND date_trunc('hour', q.ts_start, 'UTC') = date_trunc('hour', p.ts_start, 'UTC')
   )
GROUP BY p.area, date_trunc('hour', p.ts_start, 'UTC')
"""


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("area", sa.Text(), nullable=False, server_default="FI"),
        sa.Column("ts_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolution_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("price_eur_mwh", sa.Numeric(10, 3), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("area", "ts_start", "resolution_minutes", name="uq_prices_slot"),
        sa.CheckConstraint("resolution_minutes IN (15, 60)", name="ck_prices_resolution"),
    )
    op.create_index("ix_prices_area_ts_start", "prices", ["area", "ts_start"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("rows_upserted", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_table(
        "quality_results",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("check_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute(PRICES_HOURLY_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS prices_hourly")
    op.drop_table("quality_results")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_prices_area_ts_start", table_name="prices")
    op.drop_table("prices")
