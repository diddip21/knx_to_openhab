import io
import json
import os
import zipfile
from unittest.mock import Mock

import pytest
from werkzeug.datastructures import FileStorage

from web_ui.backend.jobs import JobManager
from web_ui.backend.upload_security import (
    UploadValidationError,
    remove_upload,
    store_validated_upload,
    validate_project,
)


def _archive(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in members:
            archive.writestr(name, value)


def test_rejects_path_traversal_archive(tmp_path):
    project = tmp_path / "bad.knxproj"
    _archive(project, [("../../outside.txt", "owned")])

    with pytest.raises(UploadValidationError, match="unsafe path"):
        validate_project(project, project.name)

    assert not (tmp_path.parent / "outside.txt").exists()


def test_rejects_too_many_archive_members(tmp_path):
    project = tmp_path / "many.knxprojarchive"
    _archive(project, [(f"file-{number}", "x") for number in range(3)])

    with pytest.raises(UploadValidationError, match="too many files"):
        validate_project(project, project.name, {"max_files": 2})


def test_rejects_zip_bomb_by_expanded_size(tmp_path):
    project = tmp_path / "large.knxproj"
    _archive(project, [("large.xml", "x" * 10_000)])

    with pytest.raises(UploadValidationError, match="expands beyond"):
        validate_project(
            project,
            project.name,
            {"max_uncompressed_bytes": 100, "max_compression_ratio": 1000},
        )


def test_extension_and_content_must_both_match(tmp_path):
    fake_archive = tmp_path / "fake.knxproj"
    fake_archive.write_text(json.dumps({"project": True}), encoding="utf-8")

    with pytest.raises(UploadValidationError, match="not a valid ZIP"):
        validate_project(fake_archive, fake_archive.name)


def test_invalid_json_is_rejected(tmp_path):
    project = tmp_path / "project.json"
    project.write_text("not-json", encoding="utf-8")

    with pytest.raises(UploadValidationError, match="not valid JSON"):
        validate_project(project, project.name)


def test_failed_upload_removes_isolated_directory(tmp_path):
    upload = FileStorage(stream=io.BytesIO(b"not a zip"), filename="bad.knxproj")

    with pytest.raises(UploadValidationError):
        store_validated_upload(upload, upload.filename, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_successful_upload_can_be_removed_as_a_unit(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("project.xml", "safe")
    data.seek(0)
    upload = FileStorage(stream=data, filename="safe.knxproj")

    path = store_validated_upload(upload, upload.filename, tmp_path)
    work_dir = os.path.dirname(path)
    assert os.path.isfile(path)

    remove_upload(path)
    assert not os.path.exists(work_dir)


def test_job_password_is_never_persisted(tmp_path):
    manager = JobManager(
        {
            "jobs_dir": str(tmp_path / "jobs"),
            "backups_dir": str(tmp_path / "backups"),
        }
    )
    manager.executor.shutdown()
    manager.executor = Mock()
    project = tmp_path / "project.json"
    project.write_text("{}", encoding="utf-8")

    job = manager.create_job(str(project), password="top-secret")

    persisted = (tmp_path / "jobs" / "jobs.json").read_text(encoding="utf-8")
    assert "top-secret" not in persisted
    assert "password" not in job
    assert manager._passwords[job["id"]] == "top-secret"
