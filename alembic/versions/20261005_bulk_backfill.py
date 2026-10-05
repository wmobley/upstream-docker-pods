"""add opt-in isolated bulk-backfill state

Revision ID: 20261005_bulk_backfill
Revises: 20261002_postprocessing_stages
Create Date: 2026-10-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261005_bulk_backfill"
down_revision: Union[str, Sequence[str], None] = "20261002_postprocessing_stages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "upload_imports",
        sa.Column("ingestion_mode", sa.String(length=16), nullable=False, server_default="standard"),
    )
    op.alter_column("upload_imports", "ingestion_mode", server_default=None)
    op.create_table(
        "upload_import_backfills",
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("raw_table_name", sa.String(length=128), nullable=False),
        sa.Column("shadow_table_name", sa.String(length=128), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=False, server_default="staging"),
        sa.Column("staged_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("staged_values", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shadow_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shadow_values", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("merged_values", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("merge_cursor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("target_collisions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["upload_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("import_id"),
        sa.UniqueConstraint("raw_table_name", name="uq_upload_import_backfill_raw_table"),
        sa.UniqueConstraint("shadow_table_name", name="uq_upload_import_backfill_shadow_table"),
    )


def downgrade() -> None:
    op.drop_table("upload_import_backfills")
    op.drop_column("upload_imports", "ingestion_mode")
