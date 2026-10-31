import base64
import hashlib
import importlib
import io
import json
import tarfile
import threading
from types import SimpleNamespace

import pytest

from web_ui.backend import gateway_undo
from web_ui.backend import jobs as jobs_module
from web_ui.backend.jobs import JobManager


def _prepare_deploy_manager(monkeypatch, manager, openhab_path):
    managed_config = {
        "openhab_path": str(openhab_path),
        "items_path": str(openhab_path / "items" / "knx.items"),
        "yaml_path": str(openhab_path / "yaml" / "knx.yaml"),
    }
    monkeypatch.setattr(
        importlib,
        "reload",
        lambda _module: SimpleNamespace(config=managed_config),
    )
    manager.cfg = {"openhab_path": str(openhab_path)}
    manager.backups_dir = str(openhab_path.parent / "backups")
    manager.jobs_dir = str(openhab_path.parent / "jobs")
    manager.lock = threading.Lock()
    manager.operation_lock = threading.Lock()
    manager.gateway_state_lock = threading.Lock()
    (openhab_path.parent / "backups").mkdir()
    (openhab_path.parent / "jobs").mkdir()


def test_compute_staged_stats_compares_generated_file_with_live_file(tmp_path):
    openhab_path = tmp_path / "openhab"
    live_path = openhab_path / "items" / "knx.items"
    staged_path = tmp_path / "staging" / "openhab" / "items" / "knx.items"
    live_path.parent.mkdir(parents=True)
    staged_path.parent.mkdir(parents=True)
    live_path.write_text("unchanged\nremoved\n", encoding="utf-8")
    staged_path.write_text("unchanged\nadded one\nadded two\n", encoding="utf-8")

    manager = JobManager.__new__(JobManager)
    stats = manager._compute_staged_stats({str(staged_path): str(live_path)}, str(openhab_path))

    assert stats == {
        "items/knx.items": {
            "before": 2,
            "after": 3,
            "delta": 1,
            "added": 2,
            "removed": 1,
            "staged_path": str(staged_path),
            "real_path": str(live_path),
        }
    }


def test_compute_retired_stats_reports_legacy_files_as_deletions(tmp_path):
    openhab_path = tmp_path / "openhab"
    legacy_path = openhab_path / "items" / "knx.items"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text("one\ntwo\n", encoding="utf-8")

    manager = JobManager.__new__(JobManager)
    stats = manager._compute_retired_stats([str(legacy_path)], str(openhab_path))

    assert stats["items/knx.items"] == {
        "before": 2,
        "after": 0,
        "delta": -2,
        "added": 0,
        "removed": 2,
        "staged_path": "",
        "real_path": str(legacy_path),
        "retired": True,
    }


def test_deploy_clears_legacy_model_only_after_backup(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    legacy_path = openhab_path / "items" / "knx.items"
    yaml_path = openhab_path / "yaml" / "knx.yaml"
    staging_dir = tmp_path / "staging"
    staged_yaml = staging_dir / "openhab" / "yaml" / "knx.yaml"
    staged_legacy = staging_dir / "openhab" / "items" / "knx.items"
    legacy_path.parent.mkdir(parents=True)
    yaml_path.parent.mkdir(parents=True)
    staged_yaml.parent.mkdir(parents=True)
    staged_legacy.parent.mkdir(parents=True)
    legacy_path.write_text("legacy\n", encoding="utf-8")
    yaml_path.write_text("old yaml\n", encoding="utf-8")
    staged_yaml.write_text("version: 1\n", encoding="utf-8")
    staged_legacy.write_text("", encoding="utf-8")

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    manager._jobs = {
        "job": {
            "id": "job",
            "staged": True,
            "staging_dir": str(staging_dir),
            "backups": [],
            "stage_mapping": {
                str(staged_yaml): str(yaml_path),
                str(staged_legacy): str(legacy_path),
            },
            "retired_paths": [str(legacy_path)],
        }
    }

    ok, message = manager.deploy("job")

    assert ok is True
    assert "retired 1" in message
    assert yaml_path.read_text(encoding="utf-8") == "version: 1\n"
    assert legacy_path.read_text(encoding="utf-8") == ""
    assert manager._jobs["job"]["backups"]
    with tarfile.open(manager._jobs["job"]["backups"][-1]["path"], "r:gz") as backup:
        legacy_backup = backup.extractfile("openhab/items/knx.items")
        assert legacy_backup is not None
        assert legacy_backup.read() == b"legacy\n"

    restored, _rollback_message = manager.rollback("job")

    assert restored is True
    assert legacy_path.read_text(encoding="utf-8") == "legacy\n"
    assert yaml_path.read_text(encoding="utf-8") == "old yaml\n"


def test_rollback_invalidates_gateway_deployment_metadata_and_undo_snapshot(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    openhab_path.mkdir()
    managed_file = openhab_path / "yaml" / "knx.yaml"
    managed_file.parent.mkdir()
    managed_file.write_bytes(b"new live content\n")
    backup_path = tmp_path / "backups" / "before-rollback.tar.gz"

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    backup_content = b"previous managed content\n"
    with tarfile.open(backup_path, "w:gz") as archive:
        member = tarfile.TarInfo("openhab/yaml/knx.yaml")
        member.size = len(backup_content)
        archive.addfile(member, io.BytesIO(backup_content))
    managed_paths = {"yaml_path": "yaml/knx.yaml"}
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda *_args: (str(openhab_path), managed_paths),
    )
    restored = []

    def restore_backup(archive_path, _root, relative_paths):
        restored_paths = set(relative_paths)
        with tarfile.open(archive_path, "r:gz") as archive:
            for relative in restored_paths:
                member = archive.extractfile(f"{openhab_path.name}/{relative}")
                if member is not None:
                    with member:
                        (openhab_path / relative).write_bytes(member.read())
        restored.append(restored_paths)

    monkeypatch.setattr(jobs_module, "restore_managed_files", restore_backup)
    manager._jobs = {
        "job": {
            "id": "job",
            "status": "completed",
            "deployed": True,
            "deployed_at": 2,
            "output_format": "yaml",
            "openhab_root": str(openhab_path),
            "active_things_path": "yaml/knx.yaml",
            "managed_targets": ["yaml/knx.yaml"],
            "detected_gateway_ip": "192.0.2.42",
            "backups": [{"name": backup_path.name, "path": str(backup_path)}],
        },
        "older-job": {
            "id": "older-job",
            "status": "completed",
            "deployed": True,
            "deployed_at": 1,
            "output_format": "legacy",
        },
    }
    snapshot_path = manager._gateway_undo_path()
    gateway_undo.save_snapshot(
        snapshot_path,
        {
            "job_id": "job",
            "deployment_id": "deployment-2",
            "file_content_b64": "Y29udGVudA==",
            "previous_gateway_override": "192.0.2.41",
            "openhab_root": str(openhab_path),
            "managed_path": "yaml/knx.yaml",
            "things_format": "yaml",
            "post_change_sha256": hashlib.sha256(b"current").hexdigest(),
            "post_change_gateway_override": "192.0.2.42",
        },
    )

    assert manager.get_last_deployed_things_target() is not None
    assert manager.get_last_deployed_gateway_source() is not None
    assert gateway_undo.load_snapshot(snapshot_path) is not None

    restored_ok, _message = manager.rollback("job")

    assert restored_ok is True
    assert restored == [{"yaml/knx.yaml"}]
    assert managed_file.read_bytes() == backup_content
    assert all(not job.get("deployed") for job in manager._jobs.values())
    persisted_jobs = json.loads((tmp_path / "jobs" / "jobs.json").read_text(encoding="utf-8"))
    assert all(not job.get("deployed") for job in persisted_jobs.values())
    assert manager.get_last_deployed_things_target() is None
    assert manager.get_last_deployed_gateway_source() is None
    assert gateway_undo.load_snapshot(snapshot_path) is None


def test_rollback_does_not_restore_files_when_metadata_persistence_fails(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    live_file = openhab_path / "things" / "knx.things"
    live_file.parent.mkdir(parents=True)
    live_file.write_bytes(b"current live content\n")
    backup_path = tmp_path / "backups" / "before-rollback.tar.gz"

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    backup_path.write_bytes(b"backup placeholder")
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda *_args: (str(openhab_path), {"things_path": "things/knx.things"}),
    )
    restore_calls = []
    monkeypatch.setattr(
        jobs_module,
        "restore_managed_files",
        lambda *_args: restore_calls.append(True),
    )
    manager._jobs = {
        "job": {
            "id": "job",
            "status": "completed",
            "deployed": True,
            "deployed_at": 1,
            "deployment_id": "deployment-1",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.42",
            "backups": [{"name": backup_path.name, "path": str(backup_path)}],
        }
    }
    save_jobs = jobs_module.save_jobs
    save_jobs(manager.jobs_dir, manager._jobs)

    def fail_metadata_persistence(*_args):
        raise OSError("simulated metadata persistence failure")

    monkeypatch.setattr(jobs_module, "save_jobs", fail_metadata_persistence)

    with pytest.raises(OSError, match="simulated metadata persistence failure"):
        manager.rollback("job")

    assert live_file.read_bytes() == b"current live content\n"
    assert restore_calls == []
    assert manager._jobs["job"]["deployed"] is True
    assert manager.get_last_deployed_things_target() == {
        "job_id": "job",
        "deployment_id": "deployment-1",
        "openhab_root": str(openhab_path),
        "managed_path": "things/knx.things",
        "output_format": "legacy",
        "things_format": "dsl",
    }
    assert manager.get_last_deployed_gateway_source() == {
        "job_id": "job",
        "detected_gateway_ip": "192.0.2.42",
        "things_format": "dsl",
    }


def test_rollback_restore_failure_keeps_gateway_target_unavailable(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    live_file = openhab_path / "things" / "knx.things"
    live_file.parent.mkdir(parents=True)
    live_file.write_bytes(b"current live content\n")
    backup_path = tmp_path / "backups" / "before-rollback.tar.gz"

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    backup_path.write_bytes(b"backup placeholder")
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda *_args: (str(openhab_path), {"things_path": "things/knx.things"}),
    )

    def fail_restore(*_args):
        raise OSError("simulated file restoration failure")

    monkeypatch.setattr(jobs_module, "restore_managed_files", fail_restore)
    manager._jobs = {
        "job": {
            "id": "job",
            "deployed": True,
            "deployed_at": 1,
            "deployment_id": "deployment-1",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.42",
            "backups": [{"name": backup_path.name, "path": str(backup_path)}],
        }
    }

    with pytest.raises(OSError, match="simulated file restoration failure"):
        manager.rollback("job")

    assert live_file.read_bytes() == b"current live content\n"
    persisted_jobs = json.loads((tmp_path / "jobs" / "jobs.json").read_text(encoding="utf-8"))
    assert persisted_jobs["job"]["deployed"] is False
    assert manager.get_last_deployed_things_target() is None
    assert manager.get_last_deployed_gateway_source() is None


def test_deleting_active_job_invalidates_gateway_state_without_falling_back(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    openhab_path.mkdir()
    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    manager._preview_cache = {}
    manager.queues = {}
    manager._jobs = {
        "active": {
            "id": "active",
            "status": "completed",
            "deployed": True,
            "deployed_at": 2,
            "deployment_id": "deployment-active",
            "output_format": "yaml",
            "openhab_root": str(openhab_path),
            "active_things_path": "yaml/knx.yaml",
            "managed_targets": ["yaml/knx.yaml"],
            "detected_gateway_ip": "192.0.2.42",
        },
        "older": {
            "id": "older",
            "status": "completed",
            "deployed": True,
            "deployed_at": 1,
            "deployment_id": "deployment-older",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.1",
        },
    }
    snapshot_path = manager._gateway_undo_path()
    gateway_undo.save_snapshot(
        snapshot_path,
        {
            "job_id": "active",
            "deployment_id": "deployment-active",
            "file_content_b64": "Y29udGVudA==",
            "previous_gateway_override": "",
            "openhab_root": str(openhab_path),
            "managed_path": "yaml/knx.yaml",
            "things_format": "yaml",
            "post_change_sha256": hashlib.sha256(b"current").hexdigest(),
            "post_change_gateway_override": "192.0.2.42",
        },
    )

    assert manager.delete_job("active") is True

    assert "active" not in manager._jobs
    assert all(not job.get("deployed") for job in manager._jobs.values())
    persisted_jobs = json.loads((tmp_path / "jobs" / "jobs.json").read_text(encoding="utf-8"))
    assert "active" not in persisted_jobs
    assert all(not job.get("deployed") for job in persisted_jobs.values())
    assert manager.get_last_deployed_things_target() is None
    assert manager.get_last_deployed_gateway_source() is None
    assert gateway_undo.load_snapshot(snapshot_path) is None


def test_deleting_active_job_preserves_state_when_metadata_persistence_fails(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    openhab_path.mkdir()
    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    manager._preview_cache = {}
    manager.queues = {}
    manager._jobs = {
        "active": {
            "id": "active",
            "status": "completed",
            "deployed": True,
            "deployed_at": 2,
            "deployment_id": "deployment-active",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.42",
        },
        "older": {
            "id": "older",
            "status": "completed",
            "deployed": True,
            "deployed_at": 1,
            "deployment_id": "deployment-older",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.1",
        },
    }
    jobs_before = json.loads(json.dumps(manager._jobs))
    jobs_module.save_jobs(manager.jobs_dir, manager._jobs)
    snapshot_path = manager._gateway_undo_path()
    gateway_undo.save_snapshot(
        snapshot_path,
        {
            "job_id": "active",
            "deployment_id": "deployment-active",
            "file_content_b64": "Y29udGVudA==",
            "previous_gateway_override": "",
            "openhab_root": str(openhab_path),
            "managed_path": "things/knx.things",
            "things_format": "dsl",
            "post_change_sha256": hashlib.sha256(b"current").hexdigest(),
            "post_change_gateway_override": "192.0.2.42",
        },
    )

    def fail_metadata_persistence(*_args):
        raise OSError("simulated jobs persistence failure")

    monkeypatch.setattr(jobs_module, "save_jobs", fail_metadata_persistence)

    with pytest.raises(OSError, match="simulated jobs persistence failure"):
        manager.delete_job("active")

    assert manager._jobs == jobs_before
    assert manager.get_last_deployed_things_target()["deployment_id"] == "deployment-active"
    assert manager.get_last_deployed_gateway_source()["detected_gateway_ip"] == "192.0.2.42"
    assert gateway_undo.load_snapshot(snapshot_path) is not None


def test_failed_same_job_redeploy_restores_previous_deployment_identity(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    live_file = openhab_path / "things" / "knx.things"
    staged_file = tmp_path / "staging" / "knx.things"
    live_file.parent.mkdir(parents=True)
    staged_file.parent.mkdir(parents=True)
    previous_content = b"previous deployed content\n"
    live_file.write_bytes(previous_content)
    staged_file.write_bytes(b"failed redeploy content\n")

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    managed_paths = {"things_path": "things/knx.things"}
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda *_args: (str(openhab_path), managed_paths),
    )
    manager._jobs = {
        "job": {
            "id": "job",
            "status": "completed",
            "staged": True,
            "staging_dir": str(staged_file.parent),
            "stage_mapping": {str(staged_file): str(live_file)},
            "retired_paths": [],
            "backups": [],
            "deployed": True,
            "deployed_at": 1,
            "deployment_id": "deployment-before",
            "output_format": "legacy",
            "openhab_root": str(openhab_path),
            "active_things_path": "things/knx.things",
            "managed_targets": ["things/knx.things"],
            "detected_gateway_ip": "192.0.2.42",
        }
    }
    snapshot_path = manager._gateway_undo_path()
    gateway_undo.save_snapshot(
        snapshot_path,
        {
            "job_id": "job",
            "deployment_id": "deployment-before",
            "file_content_b64": base64.b64encode(b"prior undo bytes").decode("ascii"),
            "previous_gateway_override": "192.0.2.41",
            "openhab_root": str(openhab_path),
            "managed_path": "things/knx.things",
            "things_format": "dsl",
            "post_change_sha256": hashlib.sha256(previous_content).hexdigest(),
            "post_change_gateway_override": "192.0.2.42",
        },
    )

    def deploy_staged_file(*_args):
        live_file.write_bytes(staged_file.read_bytes())
        return 1

    def restore_backup(*_args):
        live_file.write_bytes(previous_content)

    monkeypatch.setattr(jobs_module, "deploy_staged_files", deploy_staged_file)
    monkeypatch.setattr(jobs_module, "restore_managed_files", restore_backup)
    save_jobs = jobs_module.save_jobs
    save_calls = 0

    def fail_only_after_writing_staged_files(jobs_dir, jobs):
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            return save_jobs(jobs_dir, jobs)
        raise OSError("simulated deploy metadata persistence failure")

    monkeypatch.setattr(jobs_module, "save_jobs", fail_only_after_writing_staged_files)

    with pytest.raises(OSError, match="simulated deploy metadata persistence failure"):
        manager.deploy("job")

    assert save_calls == 2
    assert live_file.read_bytes() == previous_content
    assert manager._jobs["job"]["deployed"] is True
    assert manager._jobs["job"]["deployed_at"] == 1
    assert manager._jobs["job"]["deployment_id"] == "deployment-before"
    persisted_job = json.loads((tmp_path / "jobs" / "jobs.json").read_text(encoding="utf-8"))["job"]
    assert persisted_job["deployed"] is True
    assert persisted_job["deployed_at"] == 1
    assert persisted_job["deployment_id"] == "deployment-before"

    target = manager.get_last_deployed_things_target()
    assert target["deployment_id"] == "deployment-before"
    assert manager.get_last_deployed_gateway_source()["detected_gateway_ip"] == "192.0.2.42"
    snapshot = gateway_undo.load_snapshot(snapshot_path)
    assert snapshot["deployment_id"] == target["deployment_id"]
    monkeypatch.setattr(
        jobs_module,
        "read_managed_file",
        lambda *_args: live_file.read_bytes(),
    )
    assert manager._gateway_undo_available(target, str(openhab_path), managed_paths, "192.0.2.42")


def test_deploy_rejects_retirement_outside_openhab_before_writing(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    yaml_path = openhab_path / "yaml" / "knx.yaml"
    staged_yaml = tmp_path / "staging" / "openhab" / "yaml" / "knx.yaml"
    yaml_path.parent.mkdir(parents=True)
    staged_yaml.parent.mkdir(parents=True)
    staged_yaml.write_text("version: 1\n", encoding="utf-8")
    manual_file = tmp_path / "manual.items"
    manual_file.write_text("preserve me\n", encoding="utf-8")

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    manager._jobs = {
        "job": {
            "id": "job",
            "staged": True,
            "staging_dir": str(tmp_path / "staging"),
            "backups": [],
            "stage_mapping": {str(staged_yaml): str(yaml_path)},
            "retired_paths": [str(manual_file)],
        }
    }

    with pytest.raises(ValueError, match="under the OpenHAB"):
        manager.deploy("job")

    assert not yaml_path.exists()
    assert manual_file.read_text(encoding="utf-8") == "preserve me\n"
    assert list((tmp_path / "backups").iterdir()) == []


def test_deploy_rejects_symlinked_retired_file_before_writing(tmp_path, monkeypatch):
    openhab_path = tmp_path / "openhab"
    retired_path = openhab_path / "items" / "knx.items"
    yaml_path = openhab_path / "yaml" / "knx.yaml"
    staged_yaml = tmp_path / "staging" / "openhab" / "yaml" / "knx.yaml"
    retired_path.parent.mkdir(parents=True)
    yaml_path.parent.mkdir(parents=True)
    staged_yaml.parent.mkdir(parents=True)
    staged_yaml.write_text("version: 1\n", encoding="utf-8")
    external_file = tmp_path / "manual.items"
    external_file.write_text("preserve me\n", encoding="utf-8")
    retired_path.symlink_to(external_file)

    manager = JobManager.__new__(JobManager)
    _prepare_deploy_manager(monkeypatch, manager, openhab_path)
    manager._jobs = {
        "job": {
            "id": "job",
            "staged": True,
            "staging_dir": str(tmp_path / "staging"),
            "backups": [],
            "stage_mapping": {str(staged_yaml): str(yaml_path)},
            "retired_paths": [str(retired_path)],
        }
    }

    with pytest.raises(ValueError, match="single-link regular file"):
        manager.deploy("job")

    assert retired_path.is_symlink()
    assert external_file.read_text(encoding="utf-8") == "preserve me\n"
    assert not yaml_path.exists()
    assert list((tmp_path / "backups").iterdir()) == []
