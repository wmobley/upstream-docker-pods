"""add notes table

Revision ID: a1b2c3d4e5f6
Revises: b3f1b9c2d6a7
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b3f1b9c2d6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Do not also issue a raw CREATE TYPE here: the sa.Enum column below already
    # emits CREATE TYPE note_scope as part of create_table()'s DDL. Doing both
    # raises psycopg.errors.DuplicateObject on a fresh database.
    op.create_table(
        "notes",
        sa.Column("noteid", sa.Integer(), nullable=False),
        sa.Column("scope", sa.Enum("campaign", "station", "measurement", name="note_scope"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=True),
        sa.Column("measurement_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaignid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["station_id"], ["stations.stationid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["measurement_id"], ["measurements.measurementid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("noteid"),
    )
    op.create_index("ix_notes_noteid", "notes", ["noteid"])
    op.create_index("ix_notes_campaign_id", "notes", ["campaign_id"])
    op.create_index("ix_notes_station_id", "notes", ["station_id"])
    op.create_index("ix_notes_measurement_id", "notes", ["measurement_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_measurement_id", table_name="notes")
    op.drop_index("ix_notes_station_id", table_name="notes")
    op.drop_index("ix_notes_campaign_id", table_name="notes")
    op.drop_index("ix_notes_noteid", table_name="notes")
    op.drop_table("notes")
    op.execute("DROP TYPE note_scope")
