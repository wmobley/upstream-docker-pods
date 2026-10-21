"""track async post-processing stages independently

Revision ID: 20261002_postprocessing_stages
Revises: 20261002_split_postprocessing
Create Date: 2026-10-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261002_postprocessing_stages"
down_revision: Union[str, Sequence[str], None] = "20261002_split_postprocessing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "upload_imports",
        sa.Column(
            "post_processing_stage",
            sa.String(length=24),
            nullable=True,
            server_default="statistics",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE upload_imports "
            "SET post_processing_stage = CASE "
            "WHEN post_processing_status = 'completed' THEN NULL "
            "ELSE 'statistics' END "
            "WHERE post_processing_stage IS NULL"
        )
    )
    op.alter_column(
        "upload_imports",
        "post_processing_stage",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("upload_imports", "post_processing_stage")
