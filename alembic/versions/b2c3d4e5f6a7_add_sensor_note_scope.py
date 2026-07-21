"""add sensor note scope and sensor_id to notes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16

"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'sensor' to the note_scope enum (PostgreSQL-specific)
    op.execute("ALTER TYPE note_scope ADD VALUE 'sensor'")

    # Add sensor_id FK column to notes table
    op.add_column(
        "notes",
        sa.Column(
            "sensor_id",
            sa.Integer(),
            sa.ForeignKey("sensors.sensorid", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_notes_sensor_id", "notes", ["sensor_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_sensor_id", table_name="notes")
    op.drop_column("notes", "sensor_id")
    # Note: PostgreSQL does not support removing enum values;
    # downgrade would require recreating the type.
