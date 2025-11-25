# migrations/versions/20251125_0002_edgar_normalized_payload.py
"""Add normalized payload columns to sec.statement_versions.

Revision ID: 20251125_0002_norm_payload
Revises: 000000000000_idempotency_keys
Create Date: 2025-11-25

This migration:
  * Adds JSONB storage for Bloomberg-class normalized statement payloads.
  * Adds a schema version field for the normalized payload.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20251125_0002_norm_payload"
down_revision: str | None = "000000000000_idempotency_keys"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "statement_versions",
        sa.Column(
            "normalized_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="sec",
    )
    op.add_column(
        "statement_versions",
        sa.Column(
            "normalized_payload_version",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
        schema="sec",
    )


def downgrade() -> None:
    """Revert the migration (dev convenience only)."""
    op.drop_column(
        "statement_versions",
        "normalized_payload_version",
        schema="sec",
    )
    op.drop_column(
        "statement_versions",
        "normalized_payload",
        schema="sec",
    )
