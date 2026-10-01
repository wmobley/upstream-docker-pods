"""add opt-in upload ingestion mode metadata

Revision ID: 20260930_ingestion_mode
Revises: c1d2e3f4a5b6, 9e1f2a3b4c5d
Create Date: 2026-09-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260930_ingestion_mode"
down_revision: Union[str, Sequence[str], None] = (
    "c1d2e3f4a5b6",
    "9e1f2a3b4c5d",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "upload_file_events",
        sa.Column("ingestion_mode", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("upload_file_events", "ingestion_mode")
