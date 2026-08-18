"""include single-point buckets in confidence intervals function

Revision ID: 9e1f2a3b4c5d
Revises: 7a8b9c0d1e2f
Create Date: 2026-08-18 00:00:00.000000

The ``get_sensor_aggregated_measurements`` function previously filtered
out buckets with a single measurement (``point_count > 1``). For sparse
sensor data (e.g. hourly readings) this left only a handful of points,
causing the confidence-intervals endpoint to display very few data points.
This migration lowers the filter to ``point_count >= 1`` so that singleton
buckets are included. For a single-point bucket ``STDDEV()`` and the
parametric bound formulas return NULL, which the API schema now permits.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9e1f2a3b4c5d'
down_revision: Union[str, None] = '7a8b9c0d1e2f'
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
                {point_count_filter}
            ORDER BY
                measurement_time',
            interval_sql, interval_sql
        ) USING p_sensor_id, p_start_date, p_end_date, p_min_value, p_max_value;
    END;
"""


def _function_sql(second_branch: str, point_count_filter: str) -> str:
    body = FUNCTION_BODY.format(
        second_branch=second_branch, point_count_filter=point_count_filter
    )
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
    op.execute(_function_sql(second_branch, "a.point_count >= 1"))


def downgrade() -> None:
    """Downgrade schema: restore the previous filter (point_count > 1).

    The second branch is kept so the function matches the state it had after
    the 7a8b9c0d1e2f upgrade (which is what this revision supersedes).
    """
    second_branch = (
        "ELSIF p_interval = 'second' AND p_interval_value > 1 THEN\n"
        "            interval_sql := format('date_trunc(''minute'', collectiontime) +\n"
        "                                INTERVAL ''%s second'' * (EXTRACT(EPOCH FROM collectiontime)::INTEGER %% 60 / %s)',\n"
        "                                p_interval_value, p_interval_value);"
    )
    op.execute(_function_sql(second_branch, "a.point_count > 1"))
