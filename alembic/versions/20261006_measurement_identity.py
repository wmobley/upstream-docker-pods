"""add a globally unique measurement identity registry

Revision ID: 20261006_measurement_identity
Revises: 20261005_bounded_materialize
Create Date: 2026-10-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261006_measurement_identity"
down_revision: Union[str, Sequence[str], None] = "20261005_bounded_materialize"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IDENTITY_TABLE = "measurement_identity"
TRIGGER_FUNCTION = "register_measurement_identity"
TRIGGER_NAME = "measurements_register_identity_after_insert"


def upgrade() -> None:
    op.create_table(
        IDENTITY_TABLE,
        sa.Column("measurementid", sa.Integer(), nullable=False),
        sa.Column("sensorid", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["sensorid"], ["sensors.sensorid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("measurementid"),
        sa.UniqueConstraint("measurementid", "sensorid"),
    )

    # The existing 64M-row table is intentionally not copied during Alembic startup.
    # The guarded develop seed helper performs that work in resumable batches, validates
    # the result, and installs the trigger only after the identity table is complete.

    op.execute(sa.text(f"""
            CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                registered_sensorid INTEGER;
            BEGIN
                INSERT INTO {IDENTITY_TABLE} (measurementid, sensorid)
                VALUES (NEW.measurementid, NEW.sensorid)
                ON CONFLICT (measurementid) DO NOTHING;

                SELECT sensorid
                INTO registered_sensorid
                FROM {IDENTITY_TABLE}
                WHERE measurementid = NEW.measurementid;

                IF registered_sensorid IS NULL THEN
                    RAISE EXCEPTION
                        'measurement identity % could not be registered',
                        NEW.measurementid;
                END IF;

                IF registered_sensorid <> NEW.sensorid THEN
                    RAISE EXCEPTION
                        'measurement identity % is already registered to sensor %, not sensor %',
                        NEW.measurementid, registered_sensorid, NEW.sensorid;
                END IF;

                RETURN NEW;
            END;
            $$
            """))


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON measurements"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {TRIGGER_FUNCTION}()"))
    op.drop_table(IDENTITY_TABLE)
