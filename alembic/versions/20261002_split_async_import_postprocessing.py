"""separate async import post-processing state from chunk ingestion

Revision ID: 20261002_split_postprocessing
Revises: 20261001_drop_meas_indexes
Create Date: 2026-10-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261002_split_postprocessing"
down_revision: Union[str, Sequence[str], None] = "20261001_drop_meas_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "upload_imports",
        sa.Column("data_loaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "upload_imports",
        sa.Column("sensor_mapping", sa.JSON(), nullable=True),
    )
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_status",
            sa.String(length=24),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "upload_imports",
        sa.Column("post_processing_token", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "upload_imports",
        sa.Column("post_processing_error", sa.String(length=2000), nullable=True),
    )
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Imports completed by the previous worker already ran post-processing;
    # do not enqueue them again when this migration is applied.
    op.execute(
        sa.text(
            "UPDATE upload_imports "
            "SET post_processing_status = 'completed', "
            "post_processing_completed_at = completed_at, "
            "data_loaded_at = completed_at "
            "WHERE status = 'completed'"
        )
    )

    op.alter_column(
        "upload_imports",
        "post_processing_status",
        server_default=None,
    )
    op.alter_column(
        "upload_imports",
        "post_processing_attempts",
        server_default=None,
    )
    op.create_index(
        "ix_upload_imports_post_processing_claim",
        "upload_imports",
        ["status", "post_processing_status", "post_processing_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upload_imports_post_processing_claim", table_name="upload_imports"
    )
    op.drop_column("upload_imports", "post_processing_completed_at")
    op.drop_column("upload_imports", "post_processing_started_at")
    op.drop_column("upload_imports", "post_processing_error")
    op.drop_column("upload_imports", "post_processing_lease_expires_at")
    op.drop_column("upload_imports", "post_processing_token")
    op.drop_column("upload_imports", "post_processing_attempts")
    op.drop_column("upload_imports", "post_processing_status")
    op.drop_column("upload_imports", "sensor_mapping")
    op.drop_column("upload_imports", "data_loaded_at")
