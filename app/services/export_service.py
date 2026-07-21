from datetime import datetime
from typing import Iterator

from app.db.repositories.sensor_repository import SensorRepository
from app.db.repositories.measurement_repository import MeasurementRepository
from app.db.repositories.note_repository import NoteRepository
from app.db.models.note import NoteScope


class ExportService:
    """Service for handling CSV export functionality."""

    def __init__(
        self,
        sensor_repository: SensorRepository,
        measurement_repository: MeasurementRepository,
        note_repository: NoteRepository | None = None,
    ):
        self.sensor_repository = sensor_repository
        self.measurement_repository = measurement_repository
        self.note_repository = note_repository

    def export_sensors_csv(self, station_id: int) -> Iterator[str]:
        """Export sensors for a station as CSV with streaming support.

        Args:
            station_id: ID of the station to export sensors for

        Yields:
            CSV rows as strings
        """
        try:
            # Write CSV header
            yield "alias,variablename,units,description\n"

            # Stream sensors in chunks
            for sensor_chunk in self.sensor_repository.get_sensors_by_station_chunked(
                station_id, chunk_size=1000
            ):
                for sensor in sensor_chunk:
                    # Escape CSV fields properly
                    alias = (sensor.alias or "").replace('"', '""')
                    variablename = (sensor.variablename or "").replace('"', '""')
                    units = (sensor.units or "").replace('"', '""')
                    description = (sensor.description or "").replace('"', '""')

                    yield f'"{alias}","{variablename}","{units}","{description}"\n'

        except Exception as e:
            # If streaming fails, yield error information
            yield f"# Error during export: {str(e)}\n"

    def export_measurements_csv(
        self,
        station_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Iterator[str]:
        """Export measurements for a station as CSV with streaming support.

        Args:
            station_id: ID of the station to export measurements for
            start_date: Optional start date filter
            end_date: Optional end date filter

        Yields:
            CSV rows as strings
        """
        try:
            # Get unique sensor aliases for headers
            sensor_aliases = (
                self.measurement_repository.get_unique_sensor_aliases_for_station(
                    station_id
                )
            )

            # Write CSV header
            header = "collectiontime,Lat_deg,Lon_deg," + ",".join(sensor_aliases) + "\n"
            yield header

            # Process measurements in chunks with pre-grouped data
            for (
                measurement_chunk
            ) in self.measurement_repository.get_measurements_pivot_by_station_chunked(
                station_id, chunk_size=1000, start_date=start_date, end_date=end_date
            ):
                for measurement_group in measurement_chunk:
                    # Extract values from the pre-grouped data
                    collection_time = measurement_group["collection_time"]
                    lat = measurement_group["lat"]
                    lon = measurement_group["lon"]
                    sensor_values = measurement_group["sensor_values"]

                    # Build row data efficiently
                    row_data = [
                        collection_time.isoformat() if collection_time else "",
                        str(lat) if lat is not None else "",
                        str(lon) if lon is not None else "",
                    ]

                    # Add sensor values in order of aliases
                    for alias in sensor_aliases:
                        value = sensor_values.get(alias)
                        row_data.append(str(value) if value is not None else "")

                    # Write CSV row with optimized escaping
                    escaped_fields = []
                    for field in row_data:
                        escaped_field = str(field).replace('"', '""')
                        escaped_fields.append(f'"{escaped_field}"')
                    yield ",".join(escaped_fields) + "\n"

            if self.note_repository:
                yield from self._stream_notes_section(station_id)

        except Exception as e:
            # If streaming fails, yield error information
            yield f"# Error during export: {str(e)}\n"

    def _stream_notes_section(self, station_id: int) -> Iterator[str]:
        """Append a # Notes section with all station and measurement notes."""
        notes = self.note_repository.list_all_by_station(station_id)  # type: ignore[union-attr]
        if not notes:
            return
        yield "\n# Notes\n"
        yield "# scope,note_id,measurement_id,created_by,created_at,content\n"
        for note in notes:
            content = str(note.content).replace('"', '""')
            mid = str(note.measurement_id) if note.measurement_id is not None else ""
            yield f'"{note.scope.value}","{note.noteid}","{mid}","{note.created_by}","{note.created_at.isoformat()}","{content}"\n'
