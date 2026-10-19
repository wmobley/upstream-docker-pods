"""make sensor statistics refresh safe under concurrent uploads

Revision ID: 20261019_sensor_stats_conflict
Revises: 20261018_bounded_station_geom
Create Date: 2026-10-19 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_sensor_stats_conflict"
down_revision: Union[str, Sequence[str], None] = "20261018_bounded_station_geom"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make the statistics seed insert idempotent under concurrent refreshes."""
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION refresh_outdated_sensor_statistics(sensor_id INTEGER DEFAULT NULL)
            RETURNS INTEGER AS $$
            DECLARE
                updated_count INTEGER := 0;
            BEGIN
                -- Two uploads can refresh the same sensor concurrently.  The
                -- anti-join is only a snapshot, so it must be paired with an
                -- ON CONFLICT guard around the primary key insert.
                WITH sensors_without_stats AS (
                    SELECT DISTINCT m.sensorid
                    FROM measurements m
                    LEFT JOIN sensor_statistics ss ON m.sensorid = ss.sensorid
                    WHERE ss.sensorid IS NULL
                      AND (sensor_id IS NULL OR m.sensorid = sensor_id)
                )
                INSERT INTO sensor_statistics (sensorid, stats_last_updated)
                SELECT sensorid, NULL
                FROM sensors_without_stats
                ON CONFLICT (sensorid) DO NOTHING;

                -- Find sensors needing stats refresh (where last_updated is NULL).
                WITH updated_sensors AS (
                    UPDATE sensor_statistics ss
                    SET
                        max_value = stats.max_val,
                        min_value = stats.min_val,
                        avg_value = stats.avg_val,
                        stddev_value = stats.stddev_val,
                        percentile_90 = stats.p90,
                        percentile_95 = stats.p95,
                        percentile_99 = stats.p99,
                        count = stats.cnt,
                        first_measurement_value = first.first_value,
                        first_measurement_collectiontime = first.first_collectiontime,
                        last_measurement_value = latest.last_value,
                        last_measurement_collectiontime = latest.last_collectiontime,
                        stats_last_updated = NOW()
                    FROM (
                        SELECT
                            sensorid,
                            MAX(measurementvalue) AS max_val,
                            MIN(measurementvalue) AS min_val,
                            AVG(measurementvalue) AS avg_val,
                            STDDEV(measurementvalue) AS stddev_val,
                            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY measurementvalue) AS p90,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY measurementvalue) AS p95,
                            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY measurementvalue) AS p99,
                            COUNT(*) AS cnt
                        FROM measurements
                        WHERE (sensor_id IS NULL OR sensorid = sensor_id)
                        GROUP BY sensorid
                    ) stats,
                    (
                        SELECT
                            sensorid,
                            measurementvalue AS last_value,
                            collectiontime AS last_collectiontime
                        FROM (
                            SELECT
                                sensorid,
                                measurementvalue,
                                collectiontime,
                                ROW_NUMBER() OVER (PARTITION BY sensorid ORDER BY collectiontime DESC) AS rn
                            FROM measurements
                            WHERE (sensor_id IS NULL OR sensorid = sensor_id)
                        ) m
                        WHERE rn = 1
                    ) latest,
                    (
                        SELECT
                            sensorid,
                            measurementvalue AS first_value,
                            collectiontime AS first_collectiontime
                        FROM (
                            SELECT
                                sensorid,
                                measurementvalue,
                                collectiontime,
                                ROW_NUMBER() OVER (PARTITION BY sensorid ORDER BY collectiontime ASC) AS rn
                            FROM measurements
                            WHERE (sensor_id IS NULL OR sensorid = sensor_id)
                        ) m
                        WHERE rn = 1
                    ) first
                    WHERE ss.sensorid = stats.sensorid
                      AND ss.sensorid = latest.sensorid
                      AND ss.sensorid = first.sensorid
                      AND ss.stats_last_updated IS NULL
                      AND (sensor_id IS NULL OR ss.sensorid = sensor_id)
                    RETURNING ss.sensorid
                )
                SELECT COUNT(*) INTO updated_count FROM updated_sensors;

                RETURN updated_count;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )


def downgrade() -> None:
    """Keep the conflict-safe function when rolling back the marker."""
    pass
