import hashlib
import io

import pytest
from fastapi import UploadFile

from app.core.config import Settings
from app.services.upload_import_storage import cleanup_import_storage, persist_upload


def test_persist_upload_writes_atomic_file_and_digest(tmp_path):
    payload = b"collectiontime,Lat_deg,Lon_deg,temp\n"
    destination = tmp_path / "import" / "chunk-0.csv"

    size, digest = persist_upload(
        UploadFile(file=io.BytesIO(payload), filename="client-name.csv"),
        destination,
        max_bytes=1024,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert destination.read_bytes() == payload
    assert not list(destination.parent.glob("*.part"))


def test_persist_upload_rejects_wrong_digest_and_cleans_temp_file(tmp_path):
    destination = tmp_path / "chunk.csv"

    with pytest.raises(ValueError, match="SHA-256"):
        persist_upload(
            UploadFile(file=io.BytesIO(b"data"), filename="chunk.csv"),
            destination,
            max_bytes=1024,
            expected_sha256="0" * 64,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))


def test_persist_upload_enforces_byte_limit(tmp_path):
    destination = tmp_path / "chunk.csv"

    with pytest.raises(ValueError, match="exceeds"):
        persist_upload(
            UploadFile(file=io.BytesIO(b"0123456789"), filename="chunk.csv"),
            destination,
            max_bytes=5,
        )

    assert not destination.exists()


def test_cleanup_import_storage_removes_only_one_import_directory(tmp_path):
    settings = Settings(BULK_IMPORT_STORAGE_PATH=str(tmp_path))
    destination = tmp_path / "import-1" / "chunk.csv"
    destination.parent.mkdir()
    destination.write_bytes(b"data")

    cleanup_import_storage(settings, "import-1", status="completed")

    assert not destination.parent.exists()
    assert tmp_path.exists()


def test_cleanup_import_storage_rejects_path_traversal(tmp_path):
    settings = Settings(BULK_IMPORT_STORAGE_PATH=str(tmp_path))

    with pytest.raises(ValueError, match="storage key"):
        cleanup_import_storage(settings, "../outside", status="completed")


def test_cleanup_import_storage_rejects_nonterminal_import(tmp_path):
    settings = Settings(BULK_IMPORT_STORAGE_PATH=str(tmp_path))

    with pytest.raises(ValueError, match="terminal"):
        cleanup_import_storage(settings, "import-1", status="processing")
