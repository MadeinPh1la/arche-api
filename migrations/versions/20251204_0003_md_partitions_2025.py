"""Add November 2025 partitions for intraday and EOD bars.

Revision ID: 20251204_0003_md_partitions_2025
Revises: a3c43f0494a0
Create Date: 2025-12-04

This migration adds explicit partitions covering November 2025 for both
intraday and end-of-day bars. It aligns with the existing monthly partition
strategy and ensures tests inserting data for 2025-11 always have a matching
partition, regardless of when the initial bootstrap migration was executed.

Partitions created:

    - md.intraday_bars_2025_11
        PARTITION OF md_intraday_bars_parent
        FOR VALUES FROM ('2025-11-01') TO ('2025-12-01')

    - md.eod_bars_2025_11
        PARTITION OF md_eod_bars_parent
        FOR VALUES FROM ('2025-11-01') TO ('2025-12-01')
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251204_0003_md_partitions_2025"
down_revision: str | None = "a3c43f0494a0"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create November 2025 partitions for intraday and EOD bars."""
    conn = op.get_bind()

    # Intraday bars: November 2025 (UTC)
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS md.intraday_bars_2025_11
        PARTITION OF md_intraday_bars_parent
        FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
        """
    )

    # End-of-day bars: November 2025 (UTC)
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS md.eod_bars_2025_11
        PARTITION OF md_eod_bars_parent
        FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
        """
    )


def downgrade() -> None:
    """Drop November 2025 partitions for intraday and EOD bars."""
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TABLE IF EXISTS md.intraday_bars_2025_11 CASCADE;")
    conn.exec_driver_sql("DROP TABLE IF EXISTS md.eod_bars_2025_11 CASCADE;")
