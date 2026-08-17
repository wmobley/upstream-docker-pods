"""merge heads and add upload session and audit fields

Revision ID: 4e3905ac2ce5
Revises: 778a9dbdeb5e, c6b888362baa, d4e5f6a7b8c9
Create Date: 2026-08-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4e3905ac2ce5"
down_revision: Union[str, Sequence[str], None] = (
    "778a9dbdeb5e",
    "c6b888362baa",
    "d4e5f6a7b8c9",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the three migration heads and add upload session/audit fields."""
    op.add_column(
        "upload_file_events", sa.Column("upload_session_id", sa.Text(), nullable=True)
    )
    op.add_column(
        "upload_file_events", sa.Column("campaign_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "upload_file_events", sa.Column("station_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "upload_file_events", sa.Column("chunk_index", sa.Integer(), nullable=True)
    )
    op.add_column(
        "upload_file_events", sa.Column("total_chunks", sa.Integer(), nullable=True)
    )
    op.add_column(
        "upload_file_events",
        sa.Column("measurement_rows_read", sa.Integer(), nullable=True),
    )
    op.add_column(
        "upload_file_events",
        sa.Column("measurement_values_attempted", sa.Integer(), nullable=True),
    )
    op.add_column(
        "upload_file_events",
        sa.Column("measurement_values_inserted", sa.Integer(), nullable=True),
    )
    op.add_column(
        "upload_file_events",
        sa.Column("measurement_values_skipped_duplicate", sa.Integer(), nullable=True),
    )
    op.add_column(
        "upload_file_events",
        sa.Column("finalized", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "upload_file_events",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_upload_file_events_upload_session",
        "upload_file_events",
        ["campaign_id", "station_id", "upload_session_id", "chunk_index"],
        unique=False,
        postgresql_where=sa.text("upload_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove upload session/audit fields and the lookup index."""
    op.drop_index(
        "ix_upload_file_events_upload_session", table_name="upload_file_events"
    )
    op.drop_column("upload_file_events", "finalized_at")
    op.drop_column("upload_file_events", "finalized")
    op.drop_column("upload_file_events", "measurement_values_skipped_duplicate")
    op.drop_column("upload_file_events", "measurement_values_inserted")
    op.drop_column("upload_file_events", "measurement_values_attempted")
    op.drop_column("upload_file_events", "measurement_rows_read")
    op.drop_column("upload_file_events", "total_chunks")
    op.drop_column("upload_file_events", "chunk_index")
    op.drop_column("upload_file_events", "station_id")
    op.drop_column("upload_file_events", "campaign_id")
    op.drop_column("upload_file_events", "upload_session_id")
