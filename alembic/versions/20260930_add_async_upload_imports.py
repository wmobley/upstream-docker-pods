"""add durable asynchronous bulk upload imports

Revision ID: 20260930_async_imports
Revises: 20260930_ingestion_mode
Create Date: 2026-09-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260930_async_imports"
down_revision: Union[str, Sequence[str], None] = "20260930_ingestion_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_imports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("owner_username", sa.String(length=255), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("storage_key", sa.String(length=36), nullable=False),
        sa.Column("sensors_storage_key", sa.String(length=128), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("values_attempted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("values_inserted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("storage_key", name="uq_upload_import_storage_key"),
    )
    op.create_index("ix_upload_imports_campaign_id", "upload_imports", ["campaign_id"])
    op.create_index("ix_upload_imports_station_id", "upload_imports", ["station_id"])
    op.create_index("ix_upload_imports_owner_username", "upload_imports", ["owner_username"])

    op.create_table(
        "upload_import_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("upload_event_id", sa.Integer(), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("values_attempted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("values_inserted", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["import_id"], ["upload_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upload_event_id"], ["upload_file_events.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("import_id", "chunk_index", name="uq_upload_import_chunk_index"),
    )
    op.create_index("ix_upload_import_chunks_import_id", "upload_import_chunks", ["import_id"])


def downgrade() -> None:
    op.drop_index("ix_upload_import_chunks_import_id", table_name="upload_import_chunks")
    op.drop_table("upload_import_chunks")
    op.drop_index("ix_upload_imports_owner_username", table_name="upload_imports")
    op.drop_index("ix_upload_imports_station_id", table_name="upload_imports")
    op.drop_index("ix_upload_imports_campaign_id", table_name="upload_imports")
    op.drop_table("upload_imports")
