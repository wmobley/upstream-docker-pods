from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ImportStatus = Literal[
    "created",
    "receiving",
    "sealed",
    "queued",
    "processing",
    "data_loaded",
    "completed",
    "failed",
]
FinalizeImportStatus = Literal[
    "queued", "processing", "data_loaded", "completed", "failed"
]
PostProcessingStatus = Literal["pending", "processing", "completed", "failed"]


class UploadImportCreate(BaseModel):
    total_chunks: int = Field(gt=0)
    total_bytes: int = Field(gt=0)


class UploadImportChunkResponse(BaseModel):
    import_id: str
    chunk_index: int
    byte_size: int
    sha256: str
    duplicate: bool = False
    status: ImportStatus


class UploadImportStatusResponse(BaseModel):
    import_id: str
    campaign_id: int
    station_id: int
    total_chunks: int
    received_chunks: int
    processed_chunks: int
    total_bytes: int
    received_bytes: int
    rows_read: int
    values_attempted: int
    values_inserted: int
    status: ImportStatus
    post_processing_status: PostProcessingStatus
    post_processing_attempts: int
    post_processing_error: str | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    sealed_at: datetime | None = None
    data_loaded_at: datetime | None = None
    post_processing_started_at: datetime | None = None
    post_processing_completed_at: datetime | None = None
    completed_at: datetime | None = None


class UploadImportFinalizeResponse(BaseModel):
    import_id: str
    status: FinalizeImportStatus
    received_chunks: int
    total_chunks: int


def validate_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("chunk_sha256 must be a 64-character hexadecimal SHA-256 digest")
    return normalized


class UploadImportChunkMetadata(BaseModel):
    chunk_index: int = Field(ge=0)
    chunk_sha256: str

    _validate_sha256 = field_validator("chunk_sha256")(validate_sha256)
