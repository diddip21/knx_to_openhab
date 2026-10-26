"""Upload security validation for KNX project files.

Provides validation for file type, size, content, and protection against
ZIP bombs and path traversal attacks.
"""

import io
import logging
import math
import os
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional

logger = logging.getLogger(__name__)

# --- Configuration Defaults ---
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {".knxproj", ".knxprojarchive", ".json"}
MAX_ZIP_ENTRIES = 500
MAX_DECOMPRESSED_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_COMPRESSION_RATIO = 100  # compressed:uncompressed ratio
MAX_ZIP_NESTING_DEPTH = 5

# Magic bytes for validation
MAGIC_BYTES_ZIP = b"PK\x03\x04"  # ZIP archive (also .knxproj)
MAGIC_BYTES_JSON = b"{"  # JSON object


class UploadValidationError(Exception):
    """Raised when upload validation fails."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


def get_zip_validation_options(security_config: dict | None = None) -> dict[str, int | float]:
    """Return positive ZIP limits from config, falling back to safe defaults."""
    security_config = security_config or {}
    defaults = {
        "max_zip_entries": (MAX_ZIP_ENTRIES, int),
        "max_decompressed_size_bytes": (MAX_DECOMPRESSED_SIZE_BYTES, int),
        "max_compression_ratio": (MAX_COMPRESSION_RATIO, float),
    }
    options = {}
    for key, (default, value_type) in defaults.items():
        try:
            value = value_type(security_config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if not math.isfinite(value) or value <= 0:
            value = default
        options[key] = value
    return options


@dataclass
class ValidationResult:
    """Result of upload validation."""

    valid: bool
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    file_size: int = 0
    file_type: str = "unknown"


def validate_file_extension(filename: str) -> None:
    """Validate file extension against whitelist.

    Args:
        filename: Original filename to check.

    Raises:
        UploadValidationError: If extension is not allowed.
    """
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"File type '{ext}' is not supported. "
            f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            code="INVALID_EXTENSION",
        )


def validate_magic_bytes(file_content_start: bytes, filename: str) -> str:
    """Validate file content matches expected type based on magic bytes.

    Args:
        file_content_start: First 8+ bytes of the file content.
        filename: Original filename for extension check.

    Returns:
        Detected file type string ('zip', 'json', or 'unknown').

    Raises:
        UploadValidationError: If magic bytes don't match expected type.
    """
    _, ext = os.path.splitext(filename.lower())

    if file_content_start.startswith(MAGIC_BYTES_ZIP):
        detected_type = "zip"
        if ext not in {".knxproj", ".knxprojarchive"}:
            raise UploadValidationError(
                f"File content is a ZIP archive but extension '{ext}' is not a supported archive type. "
                f"Expected .knxproj or .knxprojarchive",
                code="MIME_MISMATCH",
            )
    elif file_content_start.lstrip(b" \t\r\n").startswith(MAGIC_BYTES_JSON):
        detected_type = "json"
        if ext != ".json":
            raise UploadValidationError(
                f"File content is JSON but extension is '{ext}'. Expected .json",
                code="MIME_MISMATCH",
            )
    else:
        detected_type = "unknown"
        if ext in ALLOWED_EXTENSIONS:
            raise UploadValidationError(
                f"File content does not match expected type for '{ext}'. "
                f"The file may be corrupted or is not a valid KNX project.",
                code="CONTENT_MISMATCH",
            )
        else:
            raise UploadValidationError(
                "File content is not a recognized KNX project format",
                code="CONTENT_UNKNOWN",
            )

    return detected_type


def validate_zip_safety(
    file_content: bytes | str | os.PathLike[str],
    max_zip_entries: int = MAX_ZIP_ENTRIES,
    max_decompressed_size_bytes: int = MAX_DECOMPRESSED_SIZE_BYTES,
    max_compression_ratio: float = MAX_COMPRESSION_RATIO,
    password: str | None = None,
) -> None:
    """Check ZIP archive for potential ZIP bomb or path traversal.

    This checks metadata for each archive and scans nested ZIP members without
    extracting project files to the upload directory.

    Args:
        file_content: ZIP bytes or a path to a ZIP file.
        max_zip_entries: Maximum number of entries across nested archives.
        max_decompressed_size_bytes: Maximum aggregate declared size.
        max_compression_ratio: Maximum ratio for any entry.
        password: Optional password for encrypted parent archive members.

    Raises:
        UploadValidationError: If ZIP is potentially dangerous.
    """
    try:
        source = io.BytesIO(file_content) if isinstance(file_content, bytes) else file_content
        total_entries = 0
        total_decompressed = 0
        password_bytes = password.encode("utf-8") if password else None

        def inspect_archive(archive: zipfile.ZipFile, depth: int = 0) -> None:
            nonlocal total_entries, total_decompressed
            entries = archive.infolist()

            total_entries += len(entries)
            if total_entries > max_zip_entries:
                raise UploadValidationError(
                    f"Nested archives contain {total_entries} files, maximum allowed is "
                    f"{max_zip_entries}. "
                    f"This may indicate a ZIP bomb.",
                )

            for entry in entries:
                # Check for path traversal
                posix_path = PurePosixPath(entry.filename.replace("\\", "/"))
                windows_path = PureWindowsPath(entry.filename)
                if (
                    ".." in posix_path.parts
                    or posix_path.is_absolute()
                    or windows_path.is_absolute()
                    or windows_path.drive
                ):
                    raise UploadValidationError(
                        f"Archive contains unsafe path: {entry.filename}. "
                        f"Path traversal is not allowed.",
                    )

                # Check decompressed size
                total_decompressed += entry.file_size
                if total_decompressed > max_decompressed_size_bytes:
                    raise UploadValidationError(
                        f"Archive would decompress to {total_decompressed} bytes "
                        f"(limit: {max_decompressed_size_bytes}). "
                        f"This may indicate a ZIP bomb.",
                    )

                # Check compression ratio for individual files
                if entry.compress_size > 0 and entry.file_size > 0:
                    ratio = entry.file_size / entry.compress_size
                    if ratio > max_compression_ratio:
                        raise UploadValidationError(
                            f"File '{entry.filename}' has compression ratio of {ratio:.0f}:1 "
                            f"(limit: {max_compression_ratio}:1). "
                            f"This may indicate a ZIP bomb.",
                        )

                if entry.filename.lower().endswith((".zip", ".knxproj", ".knxprojarchive")):
                    if depth >= MAX_ZIP_NESTING_DEPTH:
                        raise UploadValidationError(
                            f"Archive nesting exceeds maximum depth {MAX_ZIP_NESTING_DEPTH}.",
                        )
                    try:
                        with archive.open(entry, pwd=password_bytes) as nested_stream:
                            with zipfile.ZipFile(nested_stream) as nested_archive:
                                inspect_archive(nested_archive, depth + 1)
                    except (RuntimeError, NotImplementedError) as exc:
                        raise UploadValidationError(
                            f"Unable to inspect nested archive '{entry.filename}'. "
                            "Check the project password and archive format.",
                        ) from exc

        with zipfile.ZipFile(source) as zf:
            inspect_archive(zf)

    except zipfile.BadZipFile:
        raise UploadValidationError(
            "File is not a valid ZIP archive",
            code="INVALID_ZIP",
        )
    except UploadValidationError:
        raise
    except Exception as e:
        raise UploadValidationError(
            f"Failed to analyze archive: {e}",
            code="ZIP_ANALYSIS_FAILED",
        )


def validate_upload(
    file_content: bytes,
    filename: str,
    max_size: int = MAX_UPLOAD_SIZE_BYTES,
    max_zip_entries: int = MAX_ZIP_ENTRIES,
    max_decompressed_size_bytes: int = MAX_DECOMPRESSED_SIZE_BYTES,
    max_compression_ratio: float = MAX_COMPRESSION_RATIO,
    password: str | None = None,
) -> ValidationResult:
    """Perform full upload validation.

    Args:
        file_content: Complete file content as bytes.
        filename: Original filename.
        max_size: Maximum allowed file size in bytes.

    Returns:
        ValidationResult with validation outcome.
    """
    # 1. File size check
    file_size = len(file_content)
    if file_size > max_size:
        return ValidationResult(
            valid=False,
            error_message=f"File size ({file_size} bytes) exceeds maximum allowed size ({max_size} bytes)",
            error_code="FILE_TOO_LARGE",
            file_size=file_size,
        )

    if file_size == 0:
        return ValidationResult(
            valid=False,
            error_message="Uploaded file is empty",
            error_code="EMPTY_FILE",
            file_size=0,
        )

    # 2. Extension check
    try:
        validate_file_extension(filename)
    except UploadValidationError as e:
        return ValidationResult(
            valid=False,
            error_message=str(e),
            error_code=e.code,
            file_size=file_size,
        )

    # 3. Magic bytes check
    try:
        detected_type = validate_magic_bytes(file_content[:4096], filename)
    except UploadValidationError as e:
        return ValidationResult(
            valid=False,
            error_message=str(e),
            error_code=e.code,
            file_size=file_size,
        )

    # 4. ZIP safety check (for archives)
    if detected_type == "zip":
        try:
            validate_zip_safety(
                file_content,
                max_zip_entries=max_zip_entries,
                max_decompressed_size_bytes=max_decompressed_size_bytes,
                max_compression_ratio=max_compression_ratio,
                password=password,
            )
        except UploadValidationError as e:
            return ValidationResult(
                valid=False,
                error_message=str(e),
                error_code=e.code,
                file_size=file_size,
                file_type=detected_type,
            )

    return ValidationResult(
        valid=True,
        file_size=file_size,
        file_type=detected_type,
    )


def validate_upload_from_path(
    file_path: str,
    max_size: int = MAX_UPLOAD_SIZE_BYTES,
    max_zip_entries: int = MAX_ZIP_ENTRIES,
    max_decompressed_size_bytes: int = MAX_DECOMPRESSED_SIZE_BYTES,
    max_compression_ratio: float = MAX_COMPRESSION_RATIO,
    password: str | None = None,
) -> ValidationResult:
    """Validate an uploaded file from disk path.

    Useful for validating files already saved to disk (e.g., temp files).

    Args:
        file_path: Path to the uploaded file on disk.
        max_size: Maximum allowed file size in bytes.

    Returns:
        ValidationResult with validation outcome.
    """
    try:
        file_size = os.path.getsize(file_path)
    except OSError as e:
        return ValidationResult(
            valid=False,
            error_message=f"Cannot read file: {e}",
            error_code="FILE_READ_ERROR",
        )

    if file_size > max_size:
        return ValidationResult(
            valid=False,
            error_message=f"File size ({file_size} bytes) exceeds maximum allowed size ({max_size} bytes)",
            error_code="FILE_TOO_LARGE",
            file_size=file_size,
        )

    if file_size == 0:
        return ValidationResult(
            valid=False,
            error_message="Uploaded file is empty",
            error_code="EMPTY_FILE",
            file_size=0,
        )

    filename = os.path.basename(file_path)

    # Read only a small header for magic byte check; do not buffer the upload.
    try:
        with open(file_path, "rb") as f:
            header = f.read(4096)
    except OSError as e:
        return ValidationResult(
            valid=False,
            error_message=f"Cannot read file header: {e}",
            error_code="FILE_READ_ERROR",
        )

    # Extension check
    try:
        validate_file_extension(filename)
    except UploadValidationError as e:
        return ValidationResult(
            valid=False,
            error_message=str(e),
            error_code=e.code,
            file_size=file_size,
        )

    # Magic bytes check
    try:
        detected_type = validate_magic_bytes(header, filename)
    except UploadValidationError as e:
        return ValidationResult(
            valid=False,
            error_message=str(e),
            error_code=e.code,
            file_size=file_size,
        )

    # ZIP safety check directly against the file on disk. Passing a path to
    # ZipFile avoids loading another complete copy of a large upload into RAM.
    if detected_type == "zip":
        try:
            validate_zip_safety(
                file_path,
                max_zip_entries=max_zip_entries,
                max_decompressed_size_bytes=max_decompressed_size_bytes,
                max_compression_ratio=max_compression_ratio,
                password=password,
            )
        except UploadValidationError as e:
            return ValidationResult(
                valid=False,
                error_message=str(e),
                error_code=e.code,
                file_size=file_size,
                file_type=detected_type,
            )

    return ValidationResult(
        valid=True,
        file_size=file_size,
        file_type=detected_type,
    )
