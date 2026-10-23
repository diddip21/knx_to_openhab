import json
import os
import threading
from dataclasses import replace
from pathlib import Path

from web_ui.backend.jobs import JobManager


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


def test_deploy_retires_legacy_model_only_after_backup(tmp_path, monkeypatch):
    from knxoh_paths import get_paths as get_install_paths
    from web_ui.backend import jobs as jobs_module

    openhab_path = tmp_path / "openhab"
    legacy_path = openhab_path / "items" / "knx.items"
    yaml_path = openhab_path / "yaml" / "knx.yaml"
    staged_yaml = tmp_path / "staging" / "openhab" / "yaml" / "knx.yaml"
    legacy_path.parent.mkdir(parents=True)
    yaml_path.parent.mkdir(parents=True)
    staged_yaml.parent.mkdir(parents=True)
    legacy_path.write_text("legacy\n", encoding="utf-8")
    yaml_path.write_text("old yaml\n", encoding="utf-8")
    staged_yaml.write_text("version: 1\n", encoding="utf-8")

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    config_dir.mkdir()
    data_dir.mkdir()
    backup_dir.mkdir()
    project_root = Path(__file__).resolve().parents[1]
    config = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    config.update(
        {
            "openhab_path": str(openhab_path),
            "output_format": "yaml",
            "items_path": str(legacy_path),
            "things_path": str(openhab_path / "things" / "knx.things"),
            "sitemaps_path": str(openhab_path / "sitemaps" / "knx.sitemap"),
            "yaml_path": str(yaml_path),
            "influx_path": str(openhab_path / "persistence" / "influxdb.persist"),
            "fenster_path": str(openhab_path / "rules" / "fenster.rules"),
        }
    )
    config.pop("things_path", None)
    config.pop("sitemaps_path", None)
    (data_dir / "generator.json").write_text(json.dumps(config), encoding="utf-8")
    (config_dir / "config.json").write_text(
        json.dumps({"openhab_path": str(openhab_path)}), encoding="utf-8"
    )
    monkeypatch.setenv("KNXOH_INSTALL_DIR", str(project_root))
    monkeypatch.setenv("KNXOH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("KNXOH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KNXOH_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("KNXOH_PATHS_FILE", str(tmp_path / "missing-paths.env"))
    monkeypatch.setattr(
        "knxoh_paths.get_paths",
        lambda root=None: replace(get_install_paths(root), secrets_file=None),
    )
    retire_managed_files = jobs_module.retire_managed_files

    def assert_backup_exists_before_retirement(root, paths, managed):
        assert len(manager._jobs["job"]["backups"]) == 1
        assert os.path.isfile(manager._jobs["job"]["backups"][0]["path"])
        return retire_managed_files(root, paths, managed)

    monkeypatch.setattr(jobs_module, "retire_managed_files", assert_backup_exists_before_retirement)

    manager = JobManager.__new__(JobManager)
    manager.cfg = {"openhab_path": str(openhab_path)}
    manager.backups_dir = str(backup_dir)
    manager.jobs_dir = str(tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    manager.lock = threading.Lock()
    manager._passwords = {}
    manager._jobs = {
        "job": {
            "id": "job",
            "staged": True,
            "backups": [],
            "stage_mapping": {str(staged_yaml): str(yaml_path)},
            "retired_paths": [str(legacy_path)],
            "output_format": "yaml",
            "openhab_root": str(openhab_path),
            "staging_dir": str(tmp_path / "staging"),
        }
    }

    ok, message = manager.deploy("job")

    assert ok is True
    assert "retired 1" in message
    assert yaml_path.read_text(encoding="utf-8") == "version: 1\n"
    assert not legacy_path.exists()
    assert manager._jobs["job"]["backups"]
