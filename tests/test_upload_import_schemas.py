import pytest
from pydantic import ValidationError

from app.api.v1.schemas.upload_import import (
    UploadImportChunkMetadata,
    UploadImportCreate,
)


def test_import_create_requires_positive_manifest_values():
    assert UploadImportCreate(total_chunks=2, total_bytes=100).total_chunks == 2
    with pytest.raises(ValidationError):
        UploadImportCreate(total_chunks=0, total_bytes=100)
    with pytest.raises(ValidationError):
        UploadImportCreate(total_chunks=2, total_bytes=0)


def test_chunk_metadata_normalizes_sha256():
    metadata = UploadImportChunkMetadata(chunk_index=0, chunk_sha256="A" * 64)
    assert metadata.chunk_sha256 == "a" * 64


@pytest.mark.parametrize("digest", ["", "0" * 63, "g" * 64])
def test_chunk_metadata_rejects_invalid_sha256(digest):
    with pytest.raises(ValidationError):
        UploadImportChunkMetadata(chunk_index=0, chunk_sha256=digest)
