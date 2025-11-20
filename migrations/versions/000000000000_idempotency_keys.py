# migrations/versions/000000000000_idempotency_keys.py
"""Add idempotency_keys table for HTTP idempotency dedupe records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from stacklion_api.infrastructure.database.models.base import DEFAULT_DB_SCHEMA

# Revision identifiers, used by Alembic.
revision = "000000000000_idempotency_keys"
down_revision = "<REPLACE_WITH_PREVIOUS_REVISION>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = DEFAULT_DB_SCHEMA

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=255), primary_key=True, nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="STARTED",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMEZONE('utc', CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        schema=schema,
    )

    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = DEFAULT_DB_SCHEMA
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys", schema=schema)
    op.drop_table("idempotency_keys", schema=schema)
