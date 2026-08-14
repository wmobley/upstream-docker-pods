from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.error import Error


class UploadAudit(BaseModel):
    """Per-chunk measurement ingestion counts returned by a CSV upload."""

    measurement_rows_read: int
    measurement_values_attempted: int
    measurement_values_inserted: int
    measurement_values_skipped_duplicate: int
    sensor_alias_count: int
    row_errors: list[str] = Field(default_factory=list)


class UploadPostProcessing(BaseModel):
    """State of once-per-upload post-processing (statistics/geometry)."""

    status: str
    statistics_refreshed: bool = False
    station_geometry_refreshed: bool = False


class UploadCkanSync(BaseModel):
    """State of the deferred CKAN dataset/resource synchronization."""

    status: str
    message: str | None = None


class UploadFileCsvResponse(BaseModel):
    """Response for a CSV upload request.

    New structured fields (``audit``, ``post_processing``, ``ckan_sync``,
    ``finalized``) are added alongside the legacy response keys that existing
    clients depend on.
    """

    upload_event_id: int
    upload_session_id: str | None = None
    finalized: bool
    chunk_index: int | None = None
    total_chunks: int | None = None
    audit: UploadAudit
    post_processing: UploadPostProcessing
    ckan_sync: UploadCkanSync

    # Legacy keys preserved for backward compatibility.
    uploaded_file_sensors_stored_in_memory: bool = Field(
        alias="uploaded_file_sensors stored in memory"
    )
    uploaded_file_measurements_stored_in_memory: bool = Field(
        alias="uploaded_file_measurements stored in memory"
    )
    total_sensors_processed: int = Field(alias="Total sensors processed")
    total_measurements_added_to_database: int = Field(
        alias="Total measurements added to database"
    )
    data_processing_time: str = Field(alias="Data Processing time")
    errors: list[Error] = Field(default_factory=list)
    ckan_warnings: list[str] | None = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)
