# migrations/versions/20251124_0001_edgar_metadata.py
"""Extend sec.filings and add sec.statement_versions for EDGAR metadata.

Revision ID: 20251124_0001_edgar_metadata
Revises: 20251111_0001
Create Date: 2025-11-24

This migration:
  * Extends sec.filings with company linkage and amendment metadata.
  * Adds sec.statement_versions for versioned financial statement metadata.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251124_0001_edgar_metadata"
down_revision: str | None = "20251111_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    # ------------------------------------------------------------------
    # Extend sec.filings
    # ------------------------------------------------------------------
    op.add_column(
        "filings",
        sa.Column("company_id", sa.UUID, nullable=True),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column(
            "is_amendment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column("amendment_sequence", sa.Integer(), nullable=True),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column("primary_document", sa.String(length=256), nullable=True),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column(
            "accepted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column("filing_url", sa.Text(), nullable=True),
        schema="sec",
    )
    op.add_column(
        "filings",
        sa.Column(
            "data_source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'EDGAR'"),
        ),
        schema="sec",
    )

    # FK from filings.company_id → ref.companies.company_id
    op.create_foreign_key(
        "fk_filings_company_id_ref_companies",
        "filings",
        "companies",
        local_cols=["company_id"],
        remote_cols=["company_id"],
        source_schema="sec",
        referent_schema="ref",
        ondelete="RESTRICT",
    )

    # Indexes for common filing query patterns
    op.create_index(
        "ix_sec_filings_company_type_date",
        "filings",
        ["company_id", "form_type", "filed_at"],
        schema="sec",
    )
    op.create_index(
        "ix_sec_filings_cik_filed_at",
        "filings",
        ["cik", "filed_at"],
        schema="sec",
    )

    # ------------------------------------------------------------------
    # Create sec.statement_versions
    # ------------------------------------------------------------------
    op.create_table(
        "statement_versions",
        sa.Column("statement_version_id", sa.UUID, primary_key=True, nullable=False),
        sa.Column("company_id", sa.UUID, nullable=False),
        sa.Column("filing_id", sa.UUID, nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("accounting_standard", sa.String(length=32), nullable=False),
        sa.Column("statement_date", sa.DATE, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column(
            "is_restated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("restatement_reason", sa.String(length=255), nullable=True),
        sa.Column("version_source", sa.String(length=64), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("accession_id", sa.String(length=32), nullable=False),
        sa.Column("filing_date", sa.DATE, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "version_sequence > 0",
            name="ck_statement_versions_version_sequence_positive",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["ref.companies.company_id"],
            name="fk_statement_versions_company_id_ref_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["filing_id"],
            ["sec.filings.filing_id"],
            name="fk_statement_versions_filing_id_sec_filings",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "company_id",
            "statement_type",
            "statement_date",
            "version_sequence",
            name="uq_statement_versions_identity",
        ),
        schema="sec",
    )

    op.create_index(
        "ix_statement_versions_company_type_date",
        "statement_versions",
        ["company_id", "statement_type", "statement_date"],
        schema="sec",
    )
    op.create_index(
        "ix_statement_versions_accession_type",
        "statement_versions",
        ["accession_id", "statement_type"],
        schema="sec",
    )


def downgrade() -> None:
    """Revert the migration (dev convenience only)."""
    # Drop statement_versions indexes and table.
    op.drop_index(
        "ix_statement_versions_accession_type",
        table_name="statement_versions",
        schema="sec",
    )
    op.drop_index(
        "ix_statement_versions_company_type_date",
        table_name="statement_versions",
        schema="sec",
    )
    op.drop_table("statement_versions", schema="sec")

    # Drop filings indexes and FK.
    op.drop_index(
        "ix_sec_filings_cik_filed_at",
        table_name="filings",
        schema="sec",
    )
    op.drop_index(
        "ix_sec_filings_company_type_date",
        table_name="filings",
        schema="sec",
    )
    op.drop_constraint(
        "fk_filings_company_id_ref_companies",
        "filings",
        type_="foreignkey",
        schema="sec",
    )

    # Drop filings columns added by this migration.
    op.drop_column("filings", "data_source", schema="sec")
    op.drop_column("filings", "filing_url", schema="sec")
    op.drop_column("filings", "accepted_at", schema="sec")
    op.drop_column("filings", "primary_document", schema="sec")
    op.drop_column("filings", "amendment_sequence", schema="sec")
    op.drop_column("filings", "is_amendment", schema="sec")
    op.drop_column("filings", "company_id", schema="sec")
