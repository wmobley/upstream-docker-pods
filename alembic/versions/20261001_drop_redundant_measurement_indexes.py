"""drop redundant measurement indexes

Revision ID: 20261001_drop_meas_indexes
Revises: 20260930_async_imports
Create Date: 2026-10-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261001_drop_meas_indexes"
down_revision: Union[str, Sequence[str], None] = "20260930_async_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove indexes duplicated by the measurement primary/unique indexes."""
    op.drop_index(
        "idx_measurements_sensorid_collectiontime",
        table_name="measurements",
    )
    op.drop_index("ix_measurements_measurementid", table_name="measurements")


def downgrade() -> None:
    """Restore the redundant indexes for a reversible migration."""
    op.create_index(
        "ix_measurements_measurementid",
        "measurements",
        ["measurementid"],
    )
    op.create_index(
        "idx_measurements_sensorid_collectiontime",
        "measurements",
        ["sensorid", "collectiontime"],
    )
