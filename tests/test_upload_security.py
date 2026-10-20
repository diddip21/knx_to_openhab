"""Security tests for KNX project upload validation.

Tests cover:
- File size limits
- File extension validation
- Magic byte validation
- ZIP bomb detection
- Path traversal protection
- Password handling in job storage
- Temporary file cleanup

SEC-05: Harden KNX project uploads
"""

import io
import json
import os
import shutil

# Add project root to path
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from web_ui.backend.upload_security import (
    MAX_COMPRESSION_RATIO,
    MAX_DECOMPRESSED_SIZE_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_ZIP_ENTRIES,
    UploadValidationError,
    get_zip_validation_options,
    validate_file_extension,
    validate_magic_bytes,
    validate_upload,
    validate_upload_from_path,
    validate_zip_safety,
)


@pytest.fixture
def sample_knxproj_content():
    """Create minimal valid KNX project content (ZIP with PK header)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("project.xml", "<knxproj><project>test</project></knxproj>")
    return buf.getvalue()


@pytest.fixture
def sample_json_content():
    """Create minimal valid JSON content."""
    return json.dumps({"test": "data"}).encode("utf-8")


@pytest.fixture
def temp_upload_dir(tmp_path):
    """Create temporary upload directory."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return upload_dir


# --- File Extension Tests ---


class TestFileExtensionValidation:
    """Tests for file extension validation."""

    def test_accept_knxproj_extension(self):
        """Valid .knxproj extension should be accepted."""
        validate_file_extension("project.knxproj")

    def test_accept_knxprojarchive_extension(self):
        """Valid .knxprojarchive extension should be accepted."""
        validate_file_extension("project.knxprojarchive")

    def test_accept_json_extension(self):
        """Valid .json extension should be accepted."""
        validate_file_extension("project.json")

    def test_reject_exe_extension(self):
        """Executable files should be rejected."""
        with pytest.raises(UploadValidationError) as exc_info:
            validate_file_extension("malware.exe")
        assert exc_info.value.code == "INVALID_EXTENSION"

    def test_reject_html_extension(self):
        """HTML files should be rejected."""
        with pytest.raises(UploadValidationError):
            validate_file_extension("page.html")

    def test_reject_zip_extension(self):
        """Plain .zip files should be rejected."""
        with pytest.raises(UploadValidationError):
            validate_file_extension("archive.zip")

    def test_reject_sh_extension(self):
        """Shell scripts should be rejected."""
        with pytest.raises(UploadValidationError):
            validate_file_extension("script.sh")

    def test_double_extension_ends_with_valid_ext(self):
        """Double extension: only the final extension matters for validation."""
        # os.path.splitext("malware.exe.knxproj") -> ("malware.exe", ".knxproj")
        # This passes extension check, but magic bytes validation catches it
        # if content is not a valid ZIP
        content = b"MZ\x90\x00" + b"\x00" * 100
        result = validate_upload(content, "malware.exe.knxproj")
        assert result.valid is False  # Caught by magic bytes check

    def test_case_insensitive(self):
        """Extension check should be case-insensitive."""
        validate_file_extension("project.KNXPROJ")
        validate_file_extension("project.Json")


# --- Magic Bytes Tests ---


class TestMagicBytesValidation:
    """Tests for magic byte validation."""

    def test_detect_zip_file(self):
        """ZIP magic bytes should be detected."""
        content = b"PK\x03\x04" + b"\x00" * 12
        result = validate_magic_bytes(content, "test.knxproj")
        assert result == "zip"

    def test_detect_json_file(self):
        """JSON magic bytes should be detected."""
        content = b'{"key": "value"}'
        result = validate_magic_bytes(content, "test.json")
        assert result == "json"

    def test_reject_mismatch_zip_json(self):
        """ZIP content with .json extension should be rejected."""
        content = b"PK\x03\x04" + b"\x00" * 12
        with pytest.raises(UploadValidationError) as exc_info:
            validate_magic_bytes(content, "test.json")
        assert exc_info.value.code == "MIME_MISMATCH"

    def test_reject_mismatch_json_knxproj(self):
        """JSON content with .knxproj extension should be rejected."""
        content = b'{"key": "value"}'
        with pytest.raises(UploadValidationError):
            validate_magic_bytes(content, "test.knxproj")

    def test_reject_executable(self):
        """Executable content should be rejected."""
        content = b"MZ\x90\x00" + b"\x00" * 12
        with pytest.raises(UploadValidationError) as exc_info:
            validate_magic_bytes(content, "test.exe")
        assert exc_info.value.code == "CONTENT_UNKNOWN"


# --- ZIP Safety Tests ---


class TestZipSafety:
    """Tests for ZIP bomb and path traversal protection."""

    def test_accept_normal_zip(self, sample_knxproj_content):
        """Normal ZIP should be accepted."""
        validate_zip_safety(sample_knxproj_content)

    def test_reject_too_many_entries(self):
        """ZIP with too many entries should be rejected (ZIP bomb indicator)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(MAX_ZIP_ENTRIES + 1):
                zf.writestr(f"file_{i}.xml", f"content {i}")
        content = buf.getvalue()

        with pytest.raises(UploadValidationError) as exc_info:
            validate_zip_safety(content)
        assert "501 files" in str(exc_info.value) or "maximum allowed" in str(exc_info.value)

    def test_reject_path_traversal(self):
        """ZIP with path traversal should be rejected."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious content")
        content = buf.getvalue()

        with pytest.raises(UploadValidationError) as exc_info:
            validate_zip_safety(content)
        assert "unsafe path" in str(exc_info.value)

    def test_reject_absolute_path(self):
        """ZIP with absolute path should be rejected."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", "malicious content")
        content = buf.getvalue()

        with pytest.raises(UploadValidationError):
            validate_zip_safety(content)

    def test_configured_entry_limit_is_applied(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("one.xml", "one")
            zf.writestr("two.xml", "two")

        with pytest.raises(UploadValidationError, match="maximum allowed is 1"):
            validate_zip_safety(buf.getvalue(), max_zip_entries=1)

    def test_configured_compression_ratio_is_applied(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("large.xml", "A" * 4096)

        with pytest.raises(UploadValidationError, match="compression ratio"):
            validate_zip_safety(buf.getvalue(), max_compression_ratio=1)

    def test_nested_project_archive_is_inspected_for_decompression_size(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("0.xml", "A" * 4096)

        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("P-0001.zip", inner.getvalue())

        with pytest.raises(UploadValidationError, match="decompress"):
            validate_zip_safety(
                outer.getvalue(),
                max_decompressed_size_bytes=2000,
                max_compression_ratio=1000,
            )

    def test_reject_invalid_zip(self):
        """Invalid ZIP file should be rejected."""
        content = b"This is not a ZIP file"

        with pytest.raises(UploadValidationError) as exc_info:
            validate_zip_safety(content)
        assert exc_info.value.code == "INVALID_ZIP"


# --- Full Upload Validation Tests ---


class TestUploadValidation:
    """Tests for complete upload validation pipeline."""

    def test_accept_valid_knxproj(self, sample_knxproj_content):
        """Valid .knxproj file should be accepted."""
        result = validate_upload(sample_knxproj_content, "project.knxproj")
        assert result.valid is True
        assert result.file_type == "zip"

    def test_accept_valid_json(self, sample_json_content):
        """Valid .json file should be accepted."""
        result = validate_upload(sample_json_content, "project.json")
        assert result.valid is True
        assert result.file_type == "json"

    def test_reject_oversized_file(self):
        """File exceeding size limit should be rejected."""
        content = b"x" * (MAX_UPLOAD_SIZE_BYTES + 1)
        result = validate_upload(content, "large.knxproj")
        assert result.valid is False
        assert result.error_code == "FILE_TOO_LARGE"

    def test_reject_empty_file(self):
        """Empty file should be rejected."""
        result = validate_upload(b"", "empty.knxproj")
        assert result.valid is False
        assert result.error_code == "EMPTY_FILE"

    def test_reject_invalid_extension(self, sample_knxproj_content):
        """Invalid extension should be rejected."""
        result = validate_upload(sample_knxproj_content, "project.exe")
        assert result.valid is False
        assert result.error_code == "INVALID_EXTENSION"

    def test_reject_content_mismatch(self):
        """Content not matching extension should be rejected."""
        content = b'{"key": "value"}'
        result = validate_upload(content, "project.knxproj")
        assert result.valid is False
        assert result.error_code == "MIME_MISMATCH"


# --- Path Traversal in Tarfile Tests ---


class TestTarfileSecurity:
    """Tests for tarfile path traversal protection."""

    def test_safe_extraction_normal_tar(self, tmp_path):
        """Normal tar.gz should be extracted safely."""
        # Create a tar.gz file
        tar_path = tmp_path / "test.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            data = b"test content"
            info = tarfile.TarInfo(name="openhab/test.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        # Extract to temp directory
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                member_path = os.path.normpath(os.path.join(extract_dir, member.name))
                assert member_path.startswith(
                    os.path.normpath(extract_dir)
                ), f"Path traversal detected: {member.name}"
            tar.extractall(path=extract_dir, filter="data")

        assert (extract_dir / "openhab" / "test.txt").exists()

    def test_reject_path_traversal_tar(self, tmp_path):
        """Rollback must reject a traversal archive before extracting it."""
        tar_path = tmp_path / "malicious.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            data = b"malicious content"
            info = tarfile.TarInfo(name="../../outside.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        from web_ui.backend.jobs import JobManager

        manager = JobManager(
            {
                "jobs_dir": str(tmp_path / "jobs"),
                "backups_dir": str(tmp_path / "backups"),
                "openhab_path": str(tmp_path / "openhab"),
            }
        )
        manager._jobs["job-1"] = {"backups": [{"name": "malicious.tar.gz", "path": str(tar_path)}]}
        try:
            with pytest.raises(ValueError, match="Path traversal detected"):
                manager.rollback("job-1")
        finally:
            manager.executor.shutdown(wait=True)

        assert not (tmp_path / "outside.txt").exists()


# --- File Upload via Path Tests ---


class TestUploadFromPath:
    """Tests for validating files from disk path."""

    def test_validate_existing_file(self, temp_upload_dir, sample_knxproj_content):
        """Validate an existing file on disk."""
        file_path = temp_upload_dir / "test.knxproj"
        file_path.write_bytes(sample_knxproj_content)

        result = validate_upload_from_path(str(file_path))
        assert result.valid is True

    def test_validate_nonexistent_file(self):
        """Non-existent file should fail validation."""
        result = validate_upload_from_path("/nonexistent/file.knxproj")
        assert result.valid is False
        assert result.error_code == "FILE_READ_ERROR"

    def test_validate_oversized_file(self, temp_upload_dir):
        """Oversized file should be rejected."""
        file_path = temp_upload_dir / "large.knxproj"
        file_path.write_bytes(b"x" * (MAX_UPLOAD_SIZE_BYTES + 1))

        result = validate_upload_from_path(str(file_path))
        assert result.valid is False
        assert result.error_code == "FILE_TOO_LARGE"

    def test_validate_zip_from_path_without_reading_archive_into_memory(
        self, temp_upload_dir, sample_knxproj_content, monkeypatch
    ):
        """Disk validation must pass the path directly to ZIP inspection."""
        file_path = temp_upload_dir / "project.knxproj"
        file_path.write_bytes(sample_knxproj_content)
        inspected = []

        def inspect_archive(source, **limits):
            inspected.append((source, limits))

        monkeypatch.setattr("web_ui.backend.upload_security.validate_zip_safety", inspect_archive)

        result = validate_upload_from_path(str(file_path))

        assert result.valid is True
        assert inspected == [
            (
                str(file_path),
                {
                    "max_zip_entries": MAX_ZIP_ENTRIES,
                    "max_decompressed_size_bytes": MAX_DECOMPRESSED_SIZE_BYTES,
                    "max_compression_ratio": MAX_COMPRESSION_RATIO,
                    "password": None,
                },
            )
        ]

    def test_validate_json_with_leading_whitespace(self):
        """JSON whitespace allowed by the parser must remain accepted."""
        result = validate_upload(b' \n\t{"project": true}', "project.json")

        assert result.valid is True
        assert result.file_type == "json"


# --- Password Security Tests ---


class TestPasswordSecurity:
    """Tests for password handling in job storage."""

    def test_password_not_in_job_json(self, tmp_path):
        """Password should not be stored in jobs.json."""
        from web_ui.backend.storage import load_jobs, save_jobs

        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()

        jobs = {
            "test_job": {
                "id": "test_job",
                "name": "test.knxproj",
                "status": "completed",
                "password": "super_secret_password",  # Should be stripped
            }
        }

        save_jobs(str(jobs_dir), jobs)

        # Load and verify password is not in file
        loaded = load_jobs(str(jobs_dir))
        assert "password" not in loaded["test_job"]

    def test_password_not_in_api_response(self):
        """Password should not appear in API responses."""
        # This test verifies the job dict doesn't contain password
        from web_ui.backend.jobs import JobManager

        # Create mock config
        config = {
            "jobs_dir": tempfile.mkdtemp(),
            "backups_dir": tempfile.mkdtemp(),
            "openhab_path": tempfile.mkdtemp(),
        }

        try:
            mgr = JobManager(config)
            # Create job with password
            job = mgr.create_job(
                "/tmp/test.knxproj",
                original_name="test.knxproj",
                password="secret_password",
            )

            # Verify password is not in the returned job dict
            assert "password" not in job

            # Verify password is stored in memory only
            passwords = getattr(mgr, "_passwords", {})
            assert passwords.get(job["id"]) == "secret_password"
        finally:
            shutil.rmtree(config["jobs_dir"], ignore_errors=True)
            shutil.rmtree(config["backups_dir"], ignore_errors=True)

    def test_password_removed_when_job_submission_fails(self, tmp_path, monkeypatch):
        """Job creation failures must not leave passwords or partial jobs in memory."""
        from web_ui.backend.jobs import JobManager
        from web_ui.backend.storage import load_jobs

        config = {
            "jobs_dir": str(tmp_path / "jobs"),
            "backups_dir": str(tmp_path / "backups"),
            "openhab_path": str(tmp_path / "openhab"),
        }
        mgr = JobManager(config)

        def fail_submit(*args, **kwargs):
            raise RuntimeError("executor unavailable")

        monkeypatch.setattr(mgr.executor, "submit", fail_submit)

        with pytest.raises(RuntimeError, match="executor unavailable"):
            mgr.create_job(
                "/tmp/test.knxproj",
                original_name="test.knxproj",
                password="secret_password",
            )

        assert mgr._passwords == {}
        assert mgr._jobs == {}
        assert mgr.queues == {}
        assert load_jobs(mgr.jobs_dir) == {}
        mgr.executor.shutdown(wait=False)


# --- Configuration Constants Tests ---


class TestSecurityConfig:
    """Tests for security configuration constants."""

    def test_max_upload_size_reasonable(self):
        """Max upload size should be reasonable (10MB - 1GB)."""
        assert 10 * 1024 * 1024 <= MAX_UPLOAD_SIZE_BYTES <= 1024 * 1024 * 1024

    def test_max_zip_entries_reasonable(self):
        """Max ZIP entries should be reasonable (100 - 10000)."""
        assert 100 <= MAX_ZIP_ENTRIES <= 10000

    def test_max_decompressed_size_reasonable(self):
        """Max decompressed size should be reasonable."""
        assert MAX_DECOMPRESSED_SIZE_BYTES >= MAX_UPLOAD_SIZE_BYTES

    def test_max_compression_ratio_reasonable(self):
        """Max compression ratio should be reasonable."""
        assert 10 <= MAX_COMPRESSION_RATIO <= 1000


# --- Integration Tests ---


class TestUploadEndpointIntegration:
    """Integration tests for the upload endpoint security."""

    def test_upload_rejects_invalid_file_via_api(self, client):
        """API should reject invalid file types."""
        if client is None:
            pytest.skip("Flask test client not available")

        # Create a test file with invalid extension
        data = {
            "file": (io.BytesIO(b"test content"), "test.exe"),
        }
        response = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert response.status_code == 400
        assert "error" in response.json

    def test_upload_rejects_oversized_file_as_json(self, client, monkeypatch):
        """Flask request-size rejection must return the API's JSON error shape."""
        if client is None:
            pytest.skip("Flask test client not available")

        from web_ui.backend import app as app_module

        monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", 128)
        response = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(b"x" * 512), "project.knxproj")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 413
        assert response.is_json
        assert "maximum allowed size" in response.json["error"]

    def test_upload_validates_disk_file_with_configured_size_limit(
        self, client, tmp_path, monkeypatch
    ):
        """The upload route streams to disk and passes the configured limit."""
        if client is None:
            pytest.skip("Flask test client not available")

        from web_ui.backend import app as app_module

        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(upload_dir))
        configured_limit = 256 * 1024 * 1024
        monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", configured_limit)
        configured_zip_limits = {
            "max_zip_entries": 23,
            "max_decompressed_size_bytes": 12345,
            "max_compression_ratio": 7.5,
        }
        monkeypatch.setitem(app_module.cfg, "security", configured_zip_limits)
        job_manager = Mock()
        job_manager.create_job.return_value = {"id": "job-1"}
        monkeypatch.setattr(app_module, "job_mgr", job_manager)
        validated = {}

        def validate_path(path, max_size, **security_limits):
            validated.update(path=path, max_size=max_size, security_limits=security_limits)
            assert os.path.isfile(path)
            return SimpleNamespace(valid=True)

        monkeypatch.setattr(app_module, "validate_upload_from_path", validate_path)
        response = client.post(
            "/api/upload",
            data={"file": (io.BytesIO(b"project bytes"), "project.knxproj")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 201
        assert validated["max_size"] == configured_limit
        assert validated["security_limits"] == {
            **configured_zip_limits,
            "password": None,
        }
        assert Path(validated["path"]).name.endswith("project.knxproj")
        job_manager.create_job.assert_called_once()
        assert os.path.isfile(job_manager.create_job.call_args.args[0])

    def test_invalid_zip_settings_fall_back_to_safe_defaults(self):
        assert get_zip_validation_options(
            {
                "max_zip_entries": 0,
                "max_decompressed_size_bytes": "invalid",
                "max_compression_ratio": -1,
            }
        ) == {
            "max_zip_entries": MAX_ZIP_ENTRIES,
            "max_decompressed_size_bytes": MAX_DECOMPRESSED_SIZE_BYTES,
            "max_compression_ratio": float(MAX_COMPRESSION_RATIO),
        }


# --- Helper to create test client ---


@pytest.fixture
def client():
    """Create Flask test client if Flask is available."""
    try:
        from web_ui.backend.app import app

        app.config["TESTING"] = True
        # Disable auth for testing
        app.config["AUTH_DISABLED"] = True
        # Patch the auth config
        from web_ui.backend import app as app_module

        original_auth = app_module.cfg.get("auth", {})
        app_module.cfg["auth"] = {"enabled": False}
        with app.test_client() as client:
            yield client
        app_module.cfg["auth"] = original_auth
    except Exception:
        yield None
