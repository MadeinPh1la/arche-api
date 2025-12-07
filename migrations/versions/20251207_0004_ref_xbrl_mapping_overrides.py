"""Create ref.edgar_xbrl_mapping_overrides table.

Revision ID: 20251207_0004_xbrl_overrides
Revises: 20251204_0003_md_partitions_2025
Create Date: 2025-12-07

This migration introduces the ref.edgar_xbrl_mapping_overrides table, which
persists XBRL mapping override rules used by the domain-level override engine
in Phase E10-C.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "20251207_0004_xbrl_overrides"
down_revision: str | None = "20251204_0003_md_partitions_2025"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create ref.edgar_xbrl_mapping_overrides and supporting indexes."""
    op.create_table(
        "edgar_xbrl_mapping_overrides",
        Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("created_by", String(length=255), nullable=True),
        Column("updated_by", String(length=255), nullable=True),
        Column("scope", String(length=16), nullable=False),
        Column("source_concept", String(length=256), nullable=False),
        Column("source_taxonomy", String(length=64), nullable=True),
        Column("match_cik", String(length=10), nullable=True),
        Column("match_industry_code", String(length=32), nullable=True),
        Column("match_analyst_id", String(length=64), nullable=True),
        Column("match_dimensions", JSONB, nullable=False, server_default="{}"),
        Column("target_metric", String(length=64), nullable=True),
        Column("is_suppression", Boolean, nullable=False, server_default="false"),
        Column("priority", Integer, nullable=False, server_default="0"),
        schema="ref",
    )

    # Core lookup indexes aligned with the override engine usage pattern.
    op.create_index(
        "ix_ref_edgar_xbrl_mapping_overrides_scope",
        "edgar_xbrl_mapping_overrides",
        ["scope"],
        schema="ref",
    )
    op.create_index(
        "ix_ref_edgar_xbrl_mapping_overrides_concept_taxonomy",
        "edgar_xbrl_mapping_overrides",
        ["source_concept", "source_taxonomy"],
        schema="ref",
    )
    op.create_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_cik",
        "edgar_xbrl_mapping_overrides",
        ["match_cik"],
        schema="ref",
    )
    op.create_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_industry_code",
        "edgar_xbrl_mapping_overrides",
        ["match_industry_code"],
        schema="ref",
    )
    op.create_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_analyst_id",
        "edgar_xbrl_mapping_overrides",
        ["match_analyst_id"],
        schema="ref",
    )


def downgrade() -> None:
    """Drop ref.edgar_xbrl_mapping_overrides and its indexes."""
    op.drop_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_analyst_id",
        table_name="edgar_xbrl_mapping_overrides",
        schema="ref",
    )
    op.drop_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_industry_code",
        table_name="edgar_xbrl_mapping_overrides",
        schema="ref",
    )
    op.drop_index(
        "ix_ref_edgar_xbrl_mapping_overrides_match_cik",
        table_name="edgar_xbrl_mapping_overrides",
        schema="ref",
    )
    op.drop_index(
        "ix_ref_edgar_xbrl_mapping_overrides_concept_taxonomy",
        table_name="edgar_xbrl_mapping_overrides",
        schema="ref",
    )
    op.drop_index(
        "ix_ref_edgar_xbrl_mapping_overrides_scope",
        table_name="edgar_xbrl_mapping_overrides",
        schema="ref",
    )
    op.drop_table("edgar_xbrl_mapping_overrides", schema="ref")
