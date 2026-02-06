"""add metadata schema and metadata columns

Revision ID: b3f1b9c2d6a7
Revises: 3f6c0e5b2fdd
Create Date: 2026-02-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b3f1b9c2d6a7"
down_revision: Union[str, None] = "3f6c0e5b2fdd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metadata_schema",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(), nullable=False, index=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("field_type", sa.String(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("help_text", sa.String(), nullable=True),
        sa.Column("units", sa.String(), nullable=True),
        sa.Column("ckan_field", sa.String(), nullable=True),
        sa.Column("ckan_mode", sa.String(), nullable=False, server_default=sa.text("'extra'")),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("scope", "key", name="uq_metadata_schema_scope_key"),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_metadata_schema_scope ON metadata_schema (scope)")

    op.add_column("campaigns", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("stations", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("sensors", sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("sensors", "metadata")
    op.drop_column("stations", "metadata")
    op.drop_column("campaigns", "metadata")

    op.execute("DROP INDEX IF EXISTS ix_metadata_schema_scope")
    op.drop_table("metadata_schema")
