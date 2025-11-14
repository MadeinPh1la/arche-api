"""Bootstrap core schemas, reference tables, staging, and partitioned bar parents.

Revision ID: 20251111_0001
Revises:
Create Date: 2025-11-11

This migration:
  * Creates schemas: ref, staging, md, sec.
  * Creates reference tables: ref.exchanges, ref.companies, ref.symbols.
  * Creates staging tables: staging.ingest_runs, staging.raw_payloads (JSON, idempotent).
  * Creates partitioned parents: md_intraday_bars_parent, md_eod_bars_parent (UTC).
  * Creates sec.filings (minimal).

Notes:
  - Intraday/EOD bar partition tables are created at runtime windows (current + next month)
    as examples; production should have a monthly partition job.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251111_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    conn = op.get_bind()

    # Schemas
    for s in ("ref", "staging", "md", "sec"):
        conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {s}")

    # Reference tables
    op.create_table(
        "exchanges",
        sa.Column("mic", sa.String(10), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        schema="ref",
    )
    op.create_table(
        "companies",
        sa.Column("company_id", sa.UUID, primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("cik", sa.String(10), unique=True, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="ref",
    )
    op.create_table(
        "symbols",
        sa.Column("symbol_id", sa.UUID, primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False, index=True),
        sa.Column(
            "mic",
            sa.String(10),
            sa.ForeignKey("ref.exchanges.mic", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.UUID,
            sa.ForeignKey("ref.companies.company_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("listed_from", sa.DATE, nullable=True),
        sa.Column("listed_to", sa.DATE, nullable=True),
        sa.UniqueConstraint("ticker", "mic", name="uq_symbols_ticker_mic"),
        schema="ref",
    )

    # Staging (ingest bookkeeping + replayable raw JSON)
    op.create_table(
        "ingest_runs",
        sa.Column("run_id", sa.UUID, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result", sa.String(16), nullable=True),  # SUCCESS|NOOP|ERROR
        sa.Column("error_reason", sa.String(256), nullable=True),
        sa.UniqueConstraint("source", "endpoint", "key", name="uq_ingest_runs_dedupe"),
        schema="staging",
    )
    op.create_table(
        "raw_payloads",
        sa.Column("payload_id", sa.UUID, primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("symbol_or_cik", sa.String(64), nullable=True),
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("window_from", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("window_to", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column(
            "received_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.UniqueConstraint(
            "source",
            "endpoint",
            "symbol_or_cik",
            "as_of",
            "window_from",
            "window_to",
            name="uq_raw_payload_key",
        ),
        schema="staging",
    )

    # Partitioned parents (top-level schema for partition range simplicity)
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS md_intraday_bars_parent (
            symbol_id UUID NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            open NUMERIC(20,8) NOT NULL,
            high NUMERIC(20,8) NOT NULL,
            low  NUMERIC(20,8) NOT NULL,
            close NUMERIC(20,8) NOT NULL,
            volume NUMERIC(38,0) NOT NULL,
            provider VARCHAR(32) NOT NULL,
            PRIMARY KEY (symbol_id, ts)
        ) PARTITION BY RANGE (ts);
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS md_eod_bars_parent (
            symbol_id UUID NOT NULL,
            d DATE NOT NULL,
            open NUMERIC(20,8) NOT NULL,
            high NUMERIC(20,8) NOT NULL,
            low  NUMERIC(20,8) NOT NULL,
            close NUMERIC(20,8) NOT NULL,
            adj_close NUMERIC(20,8),
            volume NUMERIC(38,0) NOT NULL,
            provider VARCHAR(32) NOT NULL,
            PRIMARY KEY (symbol_id, d)
        ) PARTITION BY RANGE (d);
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_md_intraday_bars_ts ON md_intraday_bars_parent (ts DESC)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_md_eod_bars_d ON md_eod_bars_parent (d DESC)"
    )

    # Example partitions (current + next month)
    now = datetime.utcnow()
    months: set[tuple[int, int]] = {(now.year, now.month)}
    nxt_y, nxt_m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    months.add((nxt_y, nxt_m))
    for y, m in months:
        start = f"{y}-{m:02d}-01"
        end = f"{y + (m==12):d}-{(1 if m==12 else m+1):02d}-01"
        conn.exec_driver_sql(
            f"""
            CREATE TABLE IF NOT EXISTS md.intraday_bars_{y}_{m:02d}
            PARTITION OF md_intraday_bars_parent
            FOR VALUES FROM ('{start}') TO ('{end}');
            """
        )
        conn.exec_driver_sql(
            f"""
            CREATE TABLE IF NOT EXISTS md.eod_bars_{y}_{m:02d}
            PARTITION OF md_eod_bars_parent
            FOR VALUES FROM ('{start}') TO ('{end}');
            """
        )

    # Minimal SEC filings table
    op.create_table(
        "filings",
        sa.Column("filing_id", sa.UUID, primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False, index=True),
        sa.Column("accession", sa.String(32), unique=True, nullable=False),
        sa.Column("form_type", sa.String(16), nullable=False),
        sa.Column("filed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_of_report", sa.DATE, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        schema="sec",
    )


def downgrade() -> None:
    """Revert the migration (dev convenience only)."""
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TABLE IF EXISTS md_intraday_bars_parent CASCADE")
    conn.exec_driver_sql("DROP TABLE IF EXISTS md_eod_bars_parent CASCADE")
    op.drop_table("filings", schema="sec")
    op.drop_table("raw_payloads", schema="staging")
    op.drop_table("ingest_runs", schema="staging")
    op.drop_table("symbols", schema="ref")
    op.drop_table("companies", schema="ref")
    op.drop_table("exchanges", schema="ref")
    for s in ("sec", "staging", "md", "ref"):
        conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {s} CASCADE")
