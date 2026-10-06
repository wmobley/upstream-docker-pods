"""persist bounded backfill materialization progress

Revision ID: 20261005_bounded_materialize
Revises: 20261005_bulk_backfill
Create Date: 2026-10-05 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261005_bounded_materialize"
down_revision: Union[str, Sequence[str], None] = "20261005_bulk_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "upload_import_backfills",
        sa.Column("materialize_cursor", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("upload_import_backfills", "materialize_cursor", server_default=None)


def downgrade() -> None:
    op.drop_column("upload_import_backfills", "materialize_cursor")
