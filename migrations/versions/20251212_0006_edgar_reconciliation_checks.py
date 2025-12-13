"""Create sec.edgar_reconciliation_checks table.

Revision ID: 20251212_0006_edgar_reconciliation_checks
Revises: 20251210_0005_edgar_alignment
Create Date: 2025-12-12

Append-only reconciliation ledger of rule evaluations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20251212_0006_edgar_reconciliation_checks"
down_revision: str | None = "20251210_0005_edgar_alignment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edgar_reconciliation_checks",
        sa.Column("check_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("reconciliation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("statement_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("fiscal_year", sa.Integer, nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("version_sequence", sa.Integer, nullable=False),
        sa.Column("statement_date", sa.Date, nullable=True),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("rule_category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("expected_value", sa.Numeric(38, 6), nullable=True),
        sa.Column("actual_value", sa.Numeric(38, 6), nullable=True),
        sa.Column("delta_value", sa.Numeric(38, 6), nullable=True),
        sa.Column("dimension_key", sa.String(length=128), nullable=True),
        sa.Column("dimension_labels", postgresql.JSONB, nullable=True),
        sa.Column("notes", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="sec",
    )

    op.create_unique_constraint(
        "uq_edgar_recon_checks_run_rule_dimension",
        "edgar_reconciliation_checks",
        ["reconciliation_run_id", "rule_id", "dimension_key"],
        schema="sec",
    )

    op.create_index(
        "ix_sec_edgar_recon_checks_identity_run",
        "edgar_reconciliation_checks",
        [
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "reconciliation_run_id",
            "rule_category",
            "rule_id",
            "dimension_key",
        ],
        schema="sec",
    )

    op.create_index(
        "ix_sec_edgar_recon_checks_run_status",
        "edgar_reconciliation_checks",
        ["reconciliation_run_id", "status", "severity"],
        schema="sec",
    )

    op.create_foreign_key(
        "fk_edgar_recon_checks_statement_version",
        "edgar_reconciliation_checks",
        "statement_versions",
        ["statement_version_id"],
        ["statement_version_id"],
        source_schema="sec",
        referent_schema="sec",
    )

    op.create_foreign_key(
        "fk_edgar_recon_checks_company",
        "edgar_reconciliation_checks",
        "companies",
        ["company_id"],
        ["company_id"],
        source_schema="sec",
        referent_schema="ref",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_edgar_recon_checks_company",
        "edgar_reconciliation_checks",
        schema="sec",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_edgar_recon_checks_statement_version",
        "edgar_reconciliation_checks",
        schema="sec",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_sec_edgar_recon_checks_run_status",
        table_name="edgar_reconciliation_checks",
        schema="sec",
    )
    op.drop_index(
        "ix_sec_edgar_recon_checks_identity_run",
        table_name="edgar_reconciliation_checks",
        schema="sec",
    )
    op.drop_constraint(
        "uq_edgar_recon_checks_run_rule_dimension",
        "edgar_reconciliation_checks",
        schema="sec",
        type_="unique",
    )
    op.drop_table("edgar_reconciliation_checks", schema="sec")
