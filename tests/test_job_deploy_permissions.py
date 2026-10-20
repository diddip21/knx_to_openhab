from web_ui.backend import jobs as jobs_module
from web_ui.backend.jobs import JobManager


def _manager(tmp_path):
    manager = JobManager(
        {
            "jobs_dir": str(tmp_path / "jobs"),
            "backups_dir": str(tmp_path / "backups"),
            "openhab_path": str(tmp_path / "openhab"),
        }
    )
    manager.executor.shutdown(wait=False)
    return manager


def test_job_manager_deploy_and_rollback_use_only_managed_files(tmp_path, monkeypatch):
    root = tmp_path / "openhab"
    (root / "items").mkdir(parents=True)
    managed = root / "items" / "knx.items"
    manual = root / "items" / "manual.items"
    managed.write_text("before\n", encoding="utf-8")
    manual.write_text("manual before\n", encoding="utf-8")

    staging = tmp_path / "jobs" / "job-1" / "staging"
    staged = staging / "openhab" / "items" / "knx.items"
    staged.parent.mkdir(parents=True)
    staged.write_text("generated\n", encoding="utf-8")

    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda _config, _project_root: (str(root), {"items_path": "items/knx.items"}),
    )
    manager = _manager(tmp_path)
    manager._jobs["job-1"] = {
        "id": "job-1",
        "staged": True,
        "staging_dir": str(staging),
        "stage_mapping": {str(staged): str(managed)},
        "openhab_root": str(root),
        "managed_targets": ["items/knx.items"],
        "backups": [],
    }

    success, message = manager.deploy("job-1")
    assert success is True
    assert "Deployed 1 files" in message
    assert managed.read_text(encoding="utf-8") == "generated\n"

    managed.write_text("later change\n", encoding="utf-8")
    success, message = manager.rollback("job-1")
    assert success is True
    assert "managed files" in message
    assert managed.read_text(encoding="utf-8") == "before\n"
    assert manual.read_text(encoding="utf-8") == "manual before\n"


def test_job_manager_rejects_unmanaged_deploy_target(tmp_path, monkeypatch):
    root = tmp_path / "openhab"
    (root / "items").mkdir(parents=True)
    manual = root / "items" / "manual.items"
    manual.write_text("keep me\n", encoding="utf-8")
    staging = tmp_path / "jobs" / "job-2" / "staging"
    staged = staging / "openhab" / "items" / "manual.items"
    staged.parent.mkdir(parents=True)
    staged.write_text("overwrite\n", encoding="utf-8")

    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda _config, _project_root: (str(root), {"items_path": "items/knx.items"}),
    )
    manager = _manager(tmp_path)
    manager._jobs["job-2"] = {
        "id": "job-2",
        "staged": True,
        "staging_dir": str(staging),
        "stage_mapping": {str(staged): str(manual)},
        "openhab_root": str(root),
        "managed_targets": ["items/knx.items"],
        "backups": [],
    }

    try:
        manager.deploy("job-2")
    except ValueError as error:
        assert "not managed" in str(error)
    else:
        raise AssertionError("An unmanaged target must be rejected")

    assert manual.read_text(encoding="utf-8") == "keep me\n"
