import importlib
import tarfile
import threading
from types import SimpleNamespace

import pytest

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
