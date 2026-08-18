"""add second interval to confidence values function

Revision ID: 7a8b9c0d1e2f
Revises: c1d2e3f4a5b6
Create Date: 2026-08-18 00:00:00.000000

Extends ``get_sensor_aggregated_measurements`` with sub-minute (2s / 5s / 10s)
aggregation windows for the confidence-intervals endpoint. The new branch uses
the same epoch math pattern as the existing ``minute`` / ``hour`` custom-size
branches (bins reset at the next larger unit), so it works on every supported
PostgreSQL version.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FUNCTION_BODY = """
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
        {second_branch}
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
"""


def _function_sql(second_branch: str) -> str:
    body = FUNCTION_BODY.format(second_branch=second_branch)
    return f"""
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
    ) AS $function$
    {body}
    $function$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: truncate to the minute (the next larger unit), like the
    # minute/hour branches truncate to hour/day. Truncating to 'second'
    # would double-count the seconds component and misalign the bins.
    second_branch = (
        "ELSIF p_interval = 'second' AND p_interval_value > 1 THEN\n"
        "            interval_sql := format('date_trunc(''minute'', collectiontime) +\n"
        "                                INTERVAL ''%s second'' * (EXTRACT(EPOCH FROM collectiontime)::INTEGER %% 60 / %s)',\n"
        "                                p_interval_value, p_interval_value);"
    )
    op.execute(_function_sql(second_branch))


def downgrade() -> None:
    """Downgrade schema: restore the function without the second branch."""
    op.execute(_function_sql(""))