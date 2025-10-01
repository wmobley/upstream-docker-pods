from typing import List, Union
from datetime import datetime
from app.api.v1.schemas.measurement import MeasurementItem


def calculate_triangle_area(p1: MeasurementItem, p2: MeasurementItem, p3: MeasurementItem) -> float:
    """Calculate the area of a triangle formed by three points."""
    if not all(p.value is not None for p in [p1, p2, p3]):
        return 0.0

    # Convert timestamps to numeric values for calculation
    x1 = p1.collectiontime.timestamp()
    x2 = p2.collectiontime.timestamp()
    x3 = p3.collectiontime.timestamp()

    y1 = p1.value
    y2 = p2.value
    y3 = p3.value

    # Area = |(x1(y2-y3) + x2(y3-y1) + x3(y1-y2))/Union[2, area] = abs((x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2)) / 2.0)
    return area


def lttb(data: List[MeasurementItem], threshold: int) -> List[MeasurementItem]:
    """
    Implements the Largest-Triangle-Three-Buckets (LTTB) algorithm for downsampling time series data
    while preserving the visual characteristics of the data.

    Args:
        data: List of MeasurementItem objects to be downsampled
        threshold: Target number of points in the output

    Returns:
        Downsampled list of MeasurementItem objects
    """
    if threshold >= len(data) or threshold <= 2:
        return data

    sampled: List[MeasurementItem] = []
    bucket_size = (len(data) - 2) / (threshold - 2)

    # Always add the first point
    sampled.append(data[0])

    for i in range(threshold - 2):
        bucket_start = int((i + 0) * bucket_size) + 1
        bucket_end = int((i + 1) * bucket_size) + 1

        # Calculate average point for the bucket
        bucket_data = data[bucket_start:bucket_end]
        if not bucket_data:
            continue

        avg_x = sum(p.collectiontime.timestamp() for p in bucket_data) / len(bucket_data)
        avg_y = sum(p.value for p in bucket_data if p.value is not None) / len(bucket_data)

        # Create average point
        avg_point = MeasurementItem(
            id=-1,  # Temporary ID
            value=avg_y,
            collectiontime=datetime.fromtimestamp(avg_x),
            geometry=bucket_data[0].geometry
        )

        # Find point with maximum triangle area
        max_area : float = -1.0
        max_area_point = bucket_data[0]

        for point in bucket_data:
            area = calculate_triangle_area(
                sampled[-1],
                point,
                avg_point
            )
            if area > max_area:
                max_area = area
                max_area_point = point

        sampled.append(max_area_point)

    # Always add the last point
    sampled.append(data[-1])

    return sampled