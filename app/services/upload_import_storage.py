"""Server-owned storage helpers for the Phase 2A async import experiment."""

import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings


READ_SIZE = 1024 * 1024


def storage_root(settings: Settings) -> Path:
    root = Path(settings.BULK_IMPORT_STORAGE_PATH).expanduser()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("BULK_IMPORT_STORAGE_PATH must be a real directory")
    os.chmod(root, 0o700)
    return root


def import_directory(settings: Settings, storage_key: str) -> Path:
    root = storage_root(settings)
    directory = root / storage_key
    if directory.exists() and directory.is_symlink():
        raise ValueError("Import storage directory cannot be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def import_file_path(settings: Settings, storage_key: str, filename: str) -> Path:
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("Invalid server-generated import filename")
    path = import_directory(settings, storage_key) / filename
    if path.is_symlink():
        raise ValueError("Import storage file cannot be a symlink")
    return path


def cleanup_import_storage(settings: Settings, storage_key: str, *, status: str) -> None:
    """Remove one server-owned import directory after terminal processing.

    Only a server-generated, single-component storage key may be removed. The
    worker calls this after completion or exhausted retries; active imports
    must retain their files for resumability and investigation.
    """
    if status not in {"completed", "failed"}:
        raise ValueError("Only terminal imports may be cleaned up")
    if Path(storage_key).name != storage_key or storage_key in {"", ".", ".."}:
        raise ValueError("Invalid server-generated import storage key")
    root = storage_root(settings).resolve()
    directory = (root / storage_key).resolve()
    if directory == root or root not in directory.parents:
        raise ValueError("Import storage directory must remain below the storage root")
    if directory.is_symlink():
        raise ValueError("Import storage directory cannot be a symlink")
    if directory.exists():
        shutil.rmtree(directory)


def persist_upload(
    upload: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    """Atomically persist an upload and return its actual size and digest."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with temporary.open("xb", buffering=0) as output:
            while True:
                chunk = upload.file.read(READ_SIZE)
                if not chunk:
                    break
                byte_size += len(chunk)
                if byte_size > max_bytes:
                    raise ValueError(f"uploaded file exceeds the {max_bytes}-byte limit")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual_sha256 = digest.hexdigest()
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ValueError("uploaded file SHA-256 does not match chunk_sha256")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return byte_size, actual_sha256
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
