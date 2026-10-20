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


def test_deploy_retires_legacy_model_only_after_backup(tmp_path):
    openhab_path = tmp_path / "openhab"
    legacy_path = openhab_path / "items" / "knx.items"
    yaml_path = openhab_path / "yaml" / "knx.yaml"
    staged_yaml = tmp_path / "staging" / "openhab" / "yaml" / "knx.yaml"
    legacy_path.parent.mkdir(parents=True)
    staged_yaml.parent.mkdir(parents=True)
    legacy_path.write_text("legacy\n", encoding="utf-8")
    staged_yaml.write_text("version: 1\n", encoding="utf-8")

    manager = JobManager.__new__(JobManager)
    manager.cfg = {"openhab_path": str(openhab_path)}
    manager.backups_dir = str(tmp_path / "backups")
    manager.jobs_dir = str(tmp_path / "jobs")
    (tmp_path / "backups").mkdir()
    (tmp_path / "jobs").mkdir()
    manager._jobs = {
        "job": {
            "id": "job",
            "staged": True,
            "backups": [],
            "stage_mapping": {str(staged_yaml): str(yaml_path)},
            "retired_paths": [str(legacy_path)],
        }
    }

    ok, message = manager.deploy("job")

    assert ok is True
    assert "retired 1" in message
    assert yaml_path.read_text(encoding="utf-8") == "version: 1\n"
    assert not legacy_path.exists()
    assert manager._jobs["job"]["backups"]
