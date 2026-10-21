import tarfile
import threading

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
        lambda _config, _project_root: (
            str(root),
            {
                "items_path": "items/knx.items",
                "completeness_report": "completeness_report.json",
            },
        ),
    )
    manager = _manager(tmp_path)
    manager._jobs["job-1"] = {
        "id": "job-1",
        "staged": True,
        "staging_dir": str(staging),
        "stage_mapping": {str(staged): str(managed)},
        "openhab_root": str(root),
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


def test_job_manager_serializes_deploy_and_rollback(tmp_path, monkeypatch):
    root = tmp_path / "openhab"
    (root / "items").mkdir(parents=True)
    managed = root / "items" / "knx.items"
    managed.write_text("before\n", encoding="utf-8")
    original_tree = tmp_path / "original" / "openhab"
    (original_tree / "items").mkdir(parents=True)
    (original_tree / "items" / "knx.items").write_text("before\n", encoding="utf-8")
    original_backup = tmp_path / "backups" / "before.tar.gz"
    original_backup.parent.mkdir(parents=True)
    with tarfile.open(original_backup, "w:gz") as archive:
        archive.add(original_tree, arcname="openhab")

    staging = tmp_path / "jobs" / "job-3" / "staging"
    staged = staging / "openhab" / "items" / "knx.items"
    staged.parent.mkdir(parents=True)
    staged.write_text("deployed\n", encoding="utf-8")
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda _config, _project_root: (str(root), {"items_path": "items/knx.items"}),
    )

    manager = _manager(tmp_path)
    manager._jobs["job-3"] = {
        "id": "job-3",
        "staged": True,
        "staging_dir": str(staging),
        "stage_mapping": {str(staged): str(managed)},
        "openhab_root": str(root),
        "managed_targets": ["items/knx.items"],
        "backups": [{"name": "before.tar.gz", "path": str(original_backup), "ts": "before"}],
    }

    deploy_entered = threading.Event()
    release_deploy = threading.Event()
    rollback_started = threading.Event()
    restore_entered = threading.Event()
    active_lock = threading.Lock()
    active = 0
    max_active = 0
    real_deploy = jobs_module.deploy_staged_files
    real_restore = jobs_module.restore_managed_files

    def mark_active():
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)

    def mark_inactive():
        nonlocal active
        with active_lock:
            active -= 1

    def pause_deploy(*args, **kwargs):
        mark_active()
        deploy_entered.set()
        try:
            if not release_deploy.wait(timeout=3):
                raise TimeoutError("test did not release the deployment")
            return real_deploy(*args, **kwargs)
        finally:
            mark_inactive()

    def track_restore(*args, **kwargs):
        mark_active()
        restore_entered.set()
        try:
            return real_restore(*args, **kwargs)
        finally:
            mark_inactive()

    monkeypatch.setattr(jobs_module, "deploy_staged_files", pause_deploy)
    monkeypatch.setattr(jobs_module, "restore_managed_files", track_restore)
    results = {}
    errors = []

    def deploy_job():
        try:
            results["deploy"] = manager.deploy("job-3")
        except Exception as error:  # surfaced by the assertions below
            errors.append(error)

    def rollback_job():
        rollback_started.set()
        try:
            results["rollback"] = manager.rollback("job-3", "before.tar.gz")
        except Exception as error:  # surfaced by the assertions below
            errors.append(error)

    deploy_thread = threading.Thread(target=deploy_job)
    rollback_thread = threading.Thread(target=rollback_job)
    deploy_thread.start()
    assert deploy_entered.wait(timeout=2)
    rollback_thread.start()
    assert rollback_started.wait(timeout=2)
    restore_started_too_early = restore_entered.wait(timeout=0.2)
    release_deploy.set()
    deploy_thread.join(timeout=3)
    rollback_thread.join(timeout=3)

    assert not deploy_thread.is_alive()
    assert not rollback_thread.is_alive()
    assert not restore_started_too_early
    assert not errors
    assert results["deploy"][0] is True
    assert results["rollback"][0] is True
    assert max_active == 1
    assert managed.read_text(encoding="utf-8") == "before\n"
