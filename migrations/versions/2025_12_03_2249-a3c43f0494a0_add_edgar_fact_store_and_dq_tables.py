"""Add EDGAR fact store and DQ tables.

Revision ID: a3c43f0494a0
Revises: 20251125_0002_norm_payload
Create Date: 2025-12-03 22:49:42.572378+00:00

This migration introduces the persistent EDGAR fact store and data-quality
tables under the `sec` schema:

    - sec.edgar_normalized_facts
        Persistent normalized facts derived from canonical statement payloads.

    - sec.edgar_dq_run
        Data-quality evaluation run metadata, keyed by dq_run_id.

    - sec.edgar_fact_quality
        Fact-level quality flags and severity per DQ run.

    - sec.edgar_dq_anomalies
        Rule-level DQ anomalies emitted by the fact DQ engine.

It is intentionally scoped to these tables only and does not modify any
existing schemas, tables, or indexes outside the EDGAR fact/DQ surface.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c43f0494a0"
down_revision: str | None = "20251125_0002_norm_payload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the EDGAR fact store and DQ schema changes."""
    # ------------------------------------------------------------------ #
    # sec.edgar_dq_run                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "edgar_dq_run",
        sa.Column("dq_run_id", sa.Uuid(), nullable=False),
        sa.Column("statement_version_id", sa.Uuid(), nullable=True),
        sa.Column("cik", sa.String(length=10), nullable=True),
        sa.Column("statement_type", sa.String(length=32), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(length=8), nullable=True),
        sa.Column("version_sequence", sa.Integer(), nullable=True),
        sa.Column("rule_set_version", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["statement_version_id"],
            ["sec.statement_versions.statement_version_id"],
            name=op.f("fk_edgar_dq_run_statement_version_id_statement_versions"),
        ),
        sa.PrimaryKeyConstraint("dq_run_id", name=op.f("pk_edgar_dq_run")),
        schema="sec",
    )
    op.create_index(
        "ix_edgar_dq_run_identity_executed_at",
        "edgar_dq_run",
        [
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "executed_at",
        ],
        unique=False,
        schema="sec",
    )

    # ------------------------------------------------------------------ #
    # sec.edgar_normalized_facts                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        "edgar_normalized_facts",
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("statement_version_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("accounting_standard", sa.String(length=32), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("metric_label", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=38, scale=6), nullable=False),
        sa.Column("dimension_key", sa.String(length=128), nullable=False),
        sa.Column("dimension", sa.JSON(), nullable=True),
        sa.Column("source_line_item", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["ref.companies.company_id"],
            name=op.f("fk_edgar_normalized_facts_company_id_companies"),
        ),
        sa.ForeignKeyConstraint(
            ["statement_version_id"],
            ["sec.statement_versions.statement_version_id"],
            name=op.f("fk_edgar_normalized_facts_statement_version_id_statement_versions"),
        ),
        sa.PrimaryKeyConstraint("fact_id", name=op.f("pk_edgar_normalized_facts")),
        sa.UniqueConstraint(
            "statement_version_id",
            "metric_code",
            "dimension_key",
            name="uq_edgar_normalized_fact_identity",
        ),
        schema="sec",
    )
    op.create_index(
        "ix_edgar_normalized_facts_identity",
        "edgar_normalized_facts",
        [
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "metric_code",
            "statement_date",
        ],
        unique=False,
        schema="sec",
    )

    # ------------------------------------------------------------------ #
    # sec.edgar_dq_anomalies                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "edgar_dq_anomalies",
        sa.Column("anomaly_id", sa.Uuid(), nullable=False),
        sa.Column("dq_run_id", sa.Uuid(), nullable=False),
        sa.Column("statement_version_id", sa.Uuid(), nullable=True),
        sa.Column("metric_code", sa.String(length=64), nullable=True),
        sa.Column("dimension_key", sa.String(length=128), nullable=True),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dq_run_id"],
            ["sec.edgar_dq_run.dq_run_id"],
            name=op.f("fk_edgar_dq_anomalies_dq_run_id_edgar_dq_run"),
        ),
        sa.ForeignKeyConstraint(
            ["statement_version_id"],
            ["sec.statement_versions.statement_version_id"],
            name=op.f("fk_edgar_dq_anomalies_statement_version_id_statement_versions"),
        ),
        sa.PrimaryKeyConstraint("anomaly_id", name=op.f("pk_edgar_dq_anomalies")),
        schema="sec",
    )
    op.create_index(
        "ix_edgar_dq_anomalies_run_severity",
        "edgar_dq_anomalies",
        ["dq_run_id", "severity"],
        unique=False,
        schema="sec",
    )

    # ------------------------------------------------------------------ #
    # sec.edgar_fact_quality                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "edgar_fact_quality",
        sa.Column("fact_quality_id", sa.Uuid(), nullable=False),
        sa.Column("dq_run_id", sa.Uuid(), nullable=False),
        sa.Column("statement_version_id", sa.Uuid(), nullable=True),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(length=8), nullable=False),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("dimension_key", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("is_non_negative", sa.Boolean(), nullable=True),
        sa.Column("is_consistent_with_history", sa.Boolean(), nullable=True),
        sa.Column(
            "has_known_issue",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dq_run_id"],
            ["sec.edgar_dq_run.dq_run_id"],
            name=op.f("fk_edgar_fact_quality_dq_run_id_edgar_dq_run"),
        ),
        sa.ForeignKeyConstraint(
            ["statement_version_id"],
            ["sec.statement_versions.statement_version_id"],
            name=op.f("fk_edgar_fact_quality_statement_version_id_statement_versions"),
        ),
        sa.PrimaryKeyConstraint("fact_quality_id", name=op.f("pk_edgar_fact_quality")),
        sa.UniqueConstraint(
            "dq_run_id",
            "metric_code",
            "dimension_key",
            name="uq_edgar_fact_quality_identity",
        ),
        schema="sec",
    )
    op.create_index(
        "ix_edgar_fact_quality_statement_identity",
        "edgar_fact_quality",
        [
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "metric_code",
        ],
        unique=False,
        schema="sec",
    )


def downgrade() -> None:
    """Revert the EDGAR fact store and DQ schema changes."""
    # Drop in reverse dependency order.

    # ------------------------------------------------------------------ #
    # sec.edgar_fact_quality                                             #
    # ------------------------------------------------------------------ #
    op.drop_index(
        "ix_edgar_fact_quality_statement_identity",
        table_name="edgar_fact_quality",
        schema="sec",
    )
    op.drop_table("edgar_fact_quality", schema="sec")

    # ------------------------------------------------------------------ #
    # sec.edgar_dq_anomalies                                             #
    # ------------------------------------------------------------------ #
    op.drop_index(
        "ix_edgar_dq_anomalies_run_severity",
        table_name="edgar_dq_anomalies",
        schema="sec",
    )
    op.drop_table("edgar_dq_anomalies", schema="sec")

    # ------------------------------------------------------------------ #
    # sec.edgar_normalized_facts                                         #
    # ------------------------------------------------------------------ #
    op.drop_index(
        "ix_edgar_normalized_facts_identity",
        table_name="edgar_normalized_facts",
        schema="sec",
    )
    op.drop_table("edgar_normalized_facts", schema="sec")

    # ------------------------------------------------------------------ #
    # sec.edgar_dq_run                                                   #
    # ------------------------------------------------------------------ #
    op.drop_index(
        "ix_edgar_dq_run_identity_executed_at",
        table_name="edgar_dq_run",
        schema="sec",
    )
    op.drop_table("edgar_dq_run", schema="sec")
