# migrations/versions/20251210_0005_edgar_alignment.py
"""Create sec.edgar_statement_alignment table.

Revision ID: 20251210_0005_edgar_alignment
Revises: 20251207_0004_xbrl_overrides
Create Date: 2025-12-10

This migration introduces the sec.edgar_statement_alignment table, which
persists statement-level calendar and alignment metadata produced by the
E11 stitching engine. It is designed to support deterministic alignment
timelines and reconciliation without re-running stitching for every query.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20251210_0005_edgar_alignment"
down_revision: str | None = "20251207_0004_xbrl_overrides"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create sec.edgar_statement_alignment and supporting indexes."""
    op.create_table(
        "edgar_statement_alignment",
        sa.Column(
            "alignment_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "statement_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("statement_date", sa.Date, nullable=False),
        sa.Column("version_sequence", sa.Integer, nullable=False),
        sa.Column("fye_date", sa.Date, nullable=True),
        sa.Column(
            "is_53_week_year",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("period_start", sa.Date, nullable=True),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column("alignment_status", sa.String(length=32), nullable=False),
        sa.Column(
            "is_partial_period",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "is_off_cycle_period",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "is_irregular_calendar",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="sec",
    )

    # Unique per statement_version_id to keep a 1:1 mapping.
    op.create_unique_constraint(
        "uq_edgar_statement_alignment_statement_version",
        "edgar_statement_alignment",
        ["statement_version_id"],
        schema="sec",
    )

    # Core lookup / ordering index aligned with fact store query patterns.
    op.create_index(
        "ix_sec_edgar_statement_alignment_identity",
        "edgar_statement_alignment",
        ["cik", "statement_type", "fiscal_year", "fiscal_period", "version_sequence"],
        schema="sec",
    )

    # FK to sec.statement_versions (statement_version_id).
    op.create_foreign_key(
        "fk_edgar_statement_alignment_statement_version",
        "edgar_statement_alignment",
        "statement_versions",
        ["statement_version_id"],
        ["statement_version_id"],
        source_schema="sec",
        referent_schema="sec",
    )

    # FK to ref.companies (company_id).
    op.create_foreign_key(
        "fk_edgar_statement_alignment_company",
        "edgar_statement_alignment",
        "companies",
        ["company_id"],
        ["company_id"],
        source_schema="sec",
        referent_schema="ref",
    )


def downgrade() -> None:
    """Drop sec.edgar_statement_alignment and its constraints."""
    op.drop_constraint(
        "fk_edgar_statement_alignment_company",
        "edgar_statement_alignment",
        schema="sec",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_edgar_statement_alignment_statement_version",
        "edgar_statement_alignment",
        schema="sec",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_sec_edgar_statement_alignment_identity",
        table_name="edgar_statement_alignment",
        schema="sec",
    )
    op.drop_constraint(
        "uq_edgar_statement_alignment_statement_version",
        "edgar_statement_alignment",
        schema="sec",
        type_="unique",
    )
    op.drop_table("edgar_statement_alignment", schema="sec")
