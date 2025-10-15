"""add published state columns

Revision ID: 3f6c0e5b2fdd
Revises: cab36a8ae270
Create Date: 2025-03-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f6c0e5b2fdd"
down_revision: Union[str, None] = "cab36a8ae270"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add published state columns to core domain tables."""

    # Campaigns
    op.execute(
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"
    )

    # Stations
    op.execute(
        "ALTER TABLE stations ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE stations ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"
    )

    # Sensors
    op.execute(
        "ALTER TABLE sensors ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE sensors ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"
    )

    # Measurements
    op.execute(
        "ALTER TABLE measurements ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE measurements ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"
    )

    # Normalize any NULLs to false for safety
    op.execute("UPDATE campaigns SET is_published = COALESCE(is_published, FALSE)")
    op.execute("UPDATE stations SET is_published = COALESCE(is_published, FALSE)")
    op.execute("UPDATE sensors SET is_published = COALESCE(is_published, FALSE)")
    op.execute("UPDATE measurements SET is_published = COALESCE(is_published, FALSE)")


def downgrade() -> None:
    """Remove published state columns."""

    op.execute("ALTER TABLE measurements DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE measurements DROP COLUMN IF EXISTS is_published")

    op.execute("ALTER TABLE sensors DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE sensors DROP COLUMN IF EXISTS is_published")

    op.execute("ALTER TABLE stations DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE stations DROP COLUMN IF EXISTS is_published")

    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS published_at")
    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS is_published")
