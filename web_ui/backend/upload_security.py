"""Upload security validation for KNX project files.

Provides validation for file type, size, content, and protection against
ZIP bombs and path traversal attacks.
"""

import io
import logging
import os
import zipfile
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# --- Configuration Defaults ---
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {".knxproj", ".knxprojarchive", ".json"}
MAX_ZIP_ENTRIES = 500
MAX_DECOMPRESSED_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_COMPRESSION_RATIO = 100  # compressed:uncompressed ratio

# Magic bytes for validation
MAGIC_BYTES_ZIP = b"PK\x03\x04"  # ZIP archive (also .knxproj)
MAGIC_BYTES_JSON = b"{"  # JSON object


class UploadValidationError(Exception):
    """Raised when upload validation fails."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


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
    elif file_content_start.startswith(MAGIC_BYTES_JSON):
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


def validate_zip_safety(file_content: bytes) -> None:
    """Check ZIP archive for potential ZIP bomb or path traversal.

    This performs a pre-extraction safety check by analyzing the ZIP
    header without fully extracting contents.

    Args:
        file_content: Full content of the ZIP file.

    Raises:
        UploadValidationError: If ZIP is potentially dangerous.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
            entries = zf.infolist()

            # Check number of entries
            if len(entries) > MAX_ZIP_ENTRIES:
                raise UploadValidationError(
                    f"Archive contains {len(entries)} files, maximum allowed is {MAX_ZIP_ENTRIES}. "
                    f"This may indicate a ZIP bomb.",
                )

            total_decompressed = 0
            for entry in entries:
                # Check for path traversal
                normalized = os.path.normpath(entry.filename)
                if normalized.startswith("..") or os.path.isabs(entry.filename):
                    raise UploadValidationError(
                        f"Archive contains unsafe path: {entry.filename}. "
                        f"Path traversal is not allowed.",
                    )

                # Check decompressed size
                total_decompressed += entry.file_size
                if total_decompressed > MAX_DECOMPRESSED_SIZE_BYTES:
                    raise UploadValidationError(
                        f"Archive would decompress to {total_decompressed} bytes "
                        f"(limit: {MAX_DECOMPRESSED_SIZE_BYTES}). "
                        f"This may indicate a ZIP bomb.",
                    )

                # Check compression ratio for individual files
                if entry.compress_size > 0 and entry.file_size > 0:
                    ratio = entry.file_size / entry.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise UploadValidationError(
                            f"File '{entry.filename}' has compression ratio of {ratio:.0f}:1 "
                            f"(limit: {MAX_COMPRESSION_RATIO}:1). "
                            f"This may indicate a ZIP bomb.",
                        )

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
        detected_type = validate_magic_bytes(file_content[:16], filename)
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
            validate_zip_safety(file_content)
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

    # Read only first bytes for magic byte check
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
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

    # ZIP safety check
    if detected_type == "zip" and file_size <= MAX_DECOMPRESSED_SIZE_BYTES:
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            validate_zip_safety(content)
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
