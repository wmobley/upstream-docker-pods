"""station timezone and timestamptz collectiontime

Revision ID: c1d2e3f4a5b6
Revises: 4e3905ac2ce5
Create Date: 2026-08-18 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "4e3905ac2ce5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add stations.timezone and make measurements.collectiontime aware."""
    # 1. Required station IANA timezone; existing rows are backfilled to UTC
    #    (preserving the current interpretation of their naive data).
    op.add_column(
        "stations",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
    )

    # 2. Measurements: existing naive values were interpreted as UTC; keep
    #    their instants when converting to TIMESTAMPTZ.
    op.alter_column(
        "measurements",
        "collectiontime",
        type_=sa.DateTime(timezone=True),
        postgresql_using="collectiontime AT TIME ZONE 'UTC'",
    )

    # 3. Recreate the aggregation function with TIMESTAMPTZ arguments/returns.
    #    Argument types change, so the function must be dropped before
    #    CREATE OR REPLACE.
    op.execute("DROP FUNCTION IF EXISTS get_sensor_aggregated_measurements;")
    op.execute("""
    CREATE OR REPLACE FUNCTION get_sensor_aggregated_measurements(
        p_sensor_id INTEGER,
        p_interval TEXT DEFAULT 'hour',
        p_interval_value INTEGER DEFAULT 1,
        p_start_date TIMESTAMPTZ DEFAULT NULL,
        p_end_date TIMESTAMPTZ DEFAULT NULL,
        p_min_value FLOAT DEFAULT NULL,
        p_max_value FLOAT DEFAULT NULL
    )
    RETURNS TABLE (
        measurement_time TIMESTAMPTZ,
        value FLOAT,
        median_value FLOAT,
        point_count BIGINT,
        lower_bound FLOAT,
        upper_bound FLOAT,
        parametric_lower_bound FLOAT,
        parametric_upper_bound FLOAT,
        std_dev FLOAT,
        min_value FLOAT,
        max_value FLOAT,
        percentile_25 FLOAT,
        percentile_75 FLOAT,
        ci_method TEXT,
        confidence_level NUMERIC
    ) AS $$
    DECLARE
        interval_sql TEXT;
    BEGIN
        -- Handle custom interval sizes (e.g., 15 minutes)
        IF p_interval = 'minute' AND p_interval_value > 1 THEN
            interval_sql := format('date_trunc(''hour'', collectiontime) +
                                INTERVAL ''%s min'' * (EXTRACT(MINUTE FROM collectiontime)::INTEGER / %s)',
                                p_interval_value, p_interval_value);
        ELSIF p_interval = 'hour' AND p_interval_value > 1 THEN
            interval_sql := format('date_trunc(''day'', collectiontime) +
                                INTERVAL ''%s hour'' * (EXTRACT(HOUR FROM collectiontime)::INTEGER / %s)',
                                p_interval_value, p_interval_value);
        ELSE
            interval_sql := format('date_trunc(%L, collectiontime)', p_interval);
        END IF;

        -- Using the alternative approach without arrays to avoid potential issues
        RETURN QUERY EXECUTE format(
            'WITH aggregated_stats AS (
                SELECT
                    %s AS interval_start,
                    AVG(measurementvalue) AS avg_value,
                    COUNT(*) AS point_count,
                    STDDEV(measurementvalue) AS std_dev,
                    MIN(measurementvalue) AS min_value,
                    MAX(measurementvalue) AS max_value
                FROM
                    measurements
                WHERE
                    sensorid = $1
                    AND ($2::TIMESTAMPTZ IS NULL OR collectiontime >= $2)
                    AND ($3::TIMESTAMPTZ IS NULL OR collectiontime <= $3)
                    AND ($4::FLOAT IS NULL OR measurementvalue >= $4)
                    AND ($5::FLOAT IS NULL OR measurementvalue <= $5)
                GROUP BY
                    interval_start
                ORDER BY
                    interval_start
            ),
            percentile_stats AS (
                SELECT
                    %s AS interval_start,
                    percentile_cont(0.025) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_2_5,
                    percentile_cont(0.25) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_25,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY measurementvalue) AS median_value,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_75,
                    percentile_cont(0.975) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_97_5
                FROM
                    measurements
                WHERE
                    sensorid = $1
                    AND ($2::TIMESTAMPTZ IS NULL OR collectiontime >= $2)
                    AND ($3::TIMESTAMPTZ IS NULL OR collectiontime <= $3)
                    AND ($4::FLOAT IS NULL OR measurementvalue >= $4)
                    AND ($5::FLOAT IS NULL OR measurementvalue <= $5)
                GROUP BY
                    interval_start
            )
            SELECT
                a.interval_start AS measurement_time,
                a.avg_value AS value,
                p.median_value,
                a.point_count,
                p.percentile_2_5 AS lower_bound,
                p.percentile_97_5 AS upper_bound,
                a.avg_value - (CASE
                            WHEN a.point_count >= 30 THEN 1.96
                            WHEN a.point_count >= 20 THEN 2.09
                            WHEN a.point_count >= 10 THEN 2.23
                            ELSE 2.58
                            END) * (a.std_dev / SQRT(GREATEST(a.point_count, 1))) AS parametric_lower_bound,
                a.avg_value + (CASE
                            WHEN a.point_count >= 30 THEN 1.96
                            WHEN a.point_count >= 20 THEN 2.09
                            WHEN a.point_count >= 10 THEN 2.23
                            ELSE 2.58
                            END) * (a.std_dev / SQRT(GREATEST(a.point_count, 1))) AS parametric_upper_bound,
                a.std_dev,
                a.min_value,
                a.max_value,
                p.percentile_25,
                p.percentile_75,
                ''percentile'' AS ci_method,
                0.95 AS confidence_level
            FROM
                aggregated_stats a
            JOIN
                percentile_stats p ON a.interval_start = p.interval_start
            WHERE
                a.point_count > 1
            ORDER BY
                measurement_time',
            interval_sql, interval_sql
        ) USING p_sensor_id, p_start_date, p_end_date, p_min_value, p_max_value;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    """Downgrade schema back to naive timestamps."""
    # Restore the original function with TIMESTAMP arguments.
    op.execute("DROP FUNCTION IF EXISTS get_sensor_aggregated_measurements;")
    op.execute("""
    CREATE OR REPLACE FUNCTION get_sensor_aggregated_measurements(
        p_sensor_id INTEGER,
        p_interval TEXT DEFAULT 'hour',
        p_interval_value INTEGER DEFAULT 1,
        p_start_date TIMESTAMP DEFAULT NULL,
        p_end_date TIMESTAMP DEFAULT NULL,
        p_min_value FLOAT DEFAULT NULL,
        p_max_value FLOAT DEFAULT NULL
    )
    RETURNS TABLE (
        measurement_time TIMESTAMP,
        value FLOAT,
        median_value FLOAT,
        point_count BIGINT,
        lower_bound FLOAT,
        upper_bound FLOAT,
        parametric_lower_bound FLOAT,
        parametric_upper_bound FLOAT,
        std_dev FLOAT,
        min_value FLOAT,
        max_value FLOAT,
        percentile_25 FLOAT,
        percentile_75 FLOAT,
        ci_method TEXT,
        confidence_level NUMERIC
    ) AS $$
    DECLARE
        interval_sql TEXT;
    BEGIN
        IF p_interval = 'minute' AND p_interval_value > 1 THEN
            interval_sql := format('date_trunc(''hour'', collectiontime) +
                                INTERVAL ''%s min'' * (EXTRACT(MINUTE FROM collectiontime)::INTEGER / %s)',
                                p_interval_value, p_interval_value);
        ELSIF p_interval = 'hour' AND p_interval_value > 1 THEN
            interval_sql := format('date_trunc(''day'', collectiontime) +
                                INTERVAL ''%s hour'' * (EXTRACT(HOUR FROM collectiontime)::INTEGER / %s)',
                                p_interval_value, p_interval_value);
        ELSE
            interval_sql := format('date_trunc(%L, collectiontime)', p_interval);
        END IF;

        RETURN QUERY EXECUTE format(
            'WITH aggregated_stats AS (
                SELECT
                    %s AS interval_start,
                    AVG(measurementvalue) AS avg_value,
                    COUNT(*) AS point_count,
                    STDDEV(measurementvalue) AS std_dev,
                    MIN(measurementvalue) AS min_value,
                    MAX(measurementvalue) AS max_value
                FROM
                    measurements
                WHERE
                    sensorid = $1
                    AND ($2::TIMESTAMP IS NULL OR collectiontime >= $2)
                    AND ($3::TIMESTAMP IS NULL OR collectiontime <= $3)
                    AND ($4::FLOAT IS NULL OR measurementvalue >= $4)
                    AND ($5::FLOAT IS NULL OR measurementvalue <= $5)
                GROUP BY
                    interval_start
                ORDER BY
                    interval_start
            ),
            percentile_stats AS (
                SELECT
                    %s AS interval_start,
                    percentile_cont(0.025) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_2_5,
                    percentile_cont(0.25) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_25,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY measurementvalue) AS median_value,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_75,
                    percentile_cont(0.975) WITHIN GROUP (ORDER BY measurementvalue) AS percentile_97_5
                FROM
                    measurements
                WHERE
                    sensorid = $1
                    AND ($2::TIMESTAMP IS NULL OR collectiontime >= $2)
                    AND ($3::TIMESTAMP IS NULL OR collectiontime <= $3)
                    AND ($4::FLOAT IS NULL OR measurementvalue >= $4)
                    AND ($5::FLOAT IS NULL OR measurementvalue <= $5)
                GROUP BY
                    interval_start
            )
            SELECT
                a.interval_start AS measurement_time,
                a.avg_value AS value,
                p.median_value,
                a.point_count,
                p.percentile_2_5 AS lower_bound,
                p.percentile_97_5 AS upper_bound,
                a.avg_value - (CASE
                            WHEN a.point_count >= 30 THEN 1.96
                            WHEN a.point_count >= 20 THEN 2.09
                            WHEN a.point_count >= 10 THEN 2.23
                            ELSE 2.58
                            END) * (a.std_dev / SQRT(GREATEST(a.point_count, 1))) AS parametric_lower_bound,
                a.avg_value + (CASE
                            WHEN a.point_count >= 30 THEN 1.96
                            WHEN a.point_count >= 20 THEN 2.09
                            WHEN a.point_count >= 10 THEN 2.23
                            ELSE 2.58
                            END) * (a.std_dev / SQRT(GREATEST(a.point_count, 1))) AS parametric_upper_bound,
                a.std_dev,
                a.min_value,
                a.max_value,
                p.percentile_25,
                p.percentile_75,
                ''percentile'' AS ci_method,
                0.95 AS confidence_level
            FROM
                aggregated_stats a
            JOIN
                percentile_stats p ON a.interval_start = p.interval_start
            WHERE
                a.point_count > 1
            ORDER BY
                measurement_time',
            interval_sql, interval_sql
        ) USING p_sensor_id, p_start_date, p_end_date, p_min_value, p_max_value;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # Revert measurements.collectiontime to naive TIMESTAMP (UTC wall-clock).
    op.alter_column(
        "measurements",
        "collectiontime",
        type_=sa.DateTime(),
        postgresql_using="collectiontime AT TIME ZONE 'UTC'",
    )

    op.drop_column("stations", "timezone")
