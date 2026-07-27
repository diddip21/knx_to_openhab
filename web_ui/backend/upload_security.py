"""Validation and isolated storage for untrusted KNX project uploads."""

import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import PurePosixPath


class UploadValidationError(ValueError):
    """Raised when an uploaded project violates a security limit."""


DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 100
SUPPORTED_EXTENSIONS = (".knxprojarchive.json", ".knxprojarchive", ".knxproj", ".json")


def supported_extension(filename):
    lower_name = filename.lower()
    return next((suffix for suffix in SUPPORTED_EXTENSIONS if lower_name.endswith(suffix)), None)


def validate_project(path, filename, limits=None):
    """Validate the filename and content without extracting an archive."""
    limits = limits or {}
    extension = supported_extension(filename)
    if extension is None:
        raise UploadValidationError(
            "Unsupported file type. Use .knxproj, .knxprojarchive, or .json."
        )

    if extension.endswith(".json"):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise UploadValidationError("The uploaded .json file is not valid JSON.") from error
        if not isinstance(value, dict):
            raise UploadValidationError("The uploaded project JSON must contain an object.")
        return

    if not zipfile.is_zipfile(path):
        raise UploadValidationError("The uploaded KNX project is not a valid ZIP archive.")

    max_files = int(limits.get("max_files", DEFAULT_MAX_FILES))
    max_size = int(limits.get("max_uncompressed_bytes", DEFAULT_MAX_UNCOMPRESSED_BYTES))
    max_ratio = int(limits.get("max_compression_ratio", DEFAULT_MAX_COMPRESSION_RATIO))
    total_size = 0
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > max_files:
            raise UploadValidationError(f"Archive contains too many files (maximum {max_files}).")
        for entry in entries:
            normalized = entry.filename.replace("\\", "/")
            member = PurePosixPath(normalized)
            if member.is_absolute() or ".." in member.parts:
                raise UploadValidationError("Archive contains an unsafe path.")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UploadValidationError("Archive contains an unsupported symbolic link.")
            total_size += entry.file_size
            if total_size > max_size:
                raise UploadValidationError(
                    f"Archive expands beyond the {max_size // (1024 * 1024)} MB limit."
                )
            if entry.file_size and entry.compress_size == 0:
                raise UploadValidationError("Archive contains a suspicious compressed file.")
            if entry.compress_size and entry.file_size / entry.compress_size > max_ratio:
                raise UploadValidationError("Archive contains a suspicious compression ratio.")


def store_validated_upload(file_storage, filename, parent_dir, limits=None):
    """Store one upload in a private temporary directory and validate it."""
    limits = limits or {}
    os.makedirs(parent_dir, mode=0o700, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="upload-", dir=parent_dir)
    extension = supported_extension(filename) or ".upload"
    path = os.path.join(work_dir, f"project{extension}")
    try:
        file_storage.save(path)
        max_bytes = int(limits.get("max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES))
        if os.path.getsize(path) > max_bytes:
            raise UploadValidationError(
                f"Upload exceeds the {max_bytes // (1024 * 1024)} MB size limit."
            )
        validate_project(path, filename, limits)
        return path
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def remove_upload(path):
    """Remove the isolated directory containing an upload."""
    if path:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
