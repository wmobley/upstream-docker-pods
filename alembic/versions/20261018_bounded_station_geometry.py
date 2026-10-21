"""replace the memory-heavy station geometry aggregate

Revision ID: 20261018_bounded_station_geom
Revises: 20261006_measurement_identity
Create Date: 2026-10-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261018_bounded_station_geom"
down_revision: Union[str, Sequence[str], None] = "20261006_measurement_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Use a bounded extent aggregate for station geometry refreshes."""
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION update_station_geometry(station_id_param INTEGER)
            RETURNS VOID AS $$
            BEGIN
                UPDATE stations
                SET geometry = subquery.bbox
                FROM (
                    SELECT
                        ST_SetSRID(
                            ST_Envelope(ST_Extent(m.geometry)),
                            4326
                        ) AS bbox
                    FROM sensors AS s
                    JOIN measurements AS m ON s.sensorid = m.sensorid
                    WHERE s.stationid = station_id_param
                      AND m.geometry IS NOT NULL
                ) AS subquery
                WHERE stations.stationid = station_id_param;

                -- No matching measurements, or no matching station: clear the
                -- derived geometry without constructing a large geometry collection.
                IF NOT FOUND THEN
                    UPDATE stations
                    SET geometry = NULL
                    WHERE stationid = station_id_param;
                END IF;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )


def downgrade() -> None:
    """Keep the safe function when rolling back the migration marker.

    Reinstalling the previous ST_Collect implementation would reintroduce the
    known 1 GiB allocation failure during large uploads.
    """
    pass
