"""Maintenance admission, lifetime and readiness regression tests."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from installer.update_core.protocol import Paths
from web_ui.backend import app as app_module


@pytest.fixture
def protected():
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("isolated Linux root fixtures required")
    with tempfile.TemporaryDirectory(prefix="knxoh-maint-", dir="/root") as directory:
        root = Path(directory)
        config = root / "config"
        config.mkdir(mode=0o755)
        lease = config / ".updater-mutation.lock"
        lease.touch(mode=0o660)
        lease.chmod(0o660)
        yield Paths(root / "releases", root / "current", config)


def test_cross_process_drain_timeout_and_intent(protected):
    from installer.update_core import maintenance as m

    inode = (protected.config_dir / m.LEASE_NAME).stat().st_ino
    with m.mutation_lease(protected):
        code = (
            "from pathlib import Path; from types import SimpleNamespace; "
            "from installer.update_core.maintenance import wait_for_quiescence; "
            f"wait_for_quiescence(SimpleNamespace(config_dir=Path({str(protected.config_dir)!r})), .05)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode != 0
        assert "TimeoutError" in result.stderr
        assert not m.maintenance_requested(protected)
    with m.wait_for_quiescence(protected, 0.1):
        assert m.maintenance_requested(protected)
        with pytest.raises(m.MaintenanceError):
            with m.mutation_lease(protected):
                pytest.fail("admitted during maintenance")
        code = (
            "from pathlib import Path; from types import SimpleNamespace; "
            "from installer.update_core.maintenance import mutation_lease; "
            f"mutation_lease(SimpleNamespace(config_dir=Path({str(protected.config_dir)!r}))).__enter__()"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode != 0
        assert "MaintenanceError" in result.stderr
    assert not m.maintenance_requested(protected)
    assert (protected.config_dir / m.LEASE_NAME).stat().st_ino == inode


@pytest.mark.parametrize("unsafe", ["missing", "symlink", "hardlink", "owner", "mode"])
def test_unsafe_lease_fails_closed(protected, unsafe):
    from installer.update_core import maintenance as m

    lease = protected.config_dir / m.LEASE_NAME
    if unsafe == "missing":
        lease.unlink()
    elif unsafe == "symlink":
        lease.rename(lease.with_suffix(".other"))
        lease.symlink_to(lease.with_suffix(".other"))
    elif unsafe == "hardlink":
        os.link(lease, lease.with_suffix(".other"))
    elif unsafe == "owner":
        os.chown(lease, 1000, 1000)
    else:
        lease.chmod(0o666)
    with pytest.raises(m.MaintenanceError):
        with m.mutation_lease(protected):
            pytest.fail("unsafe lease admitted")


def test_unprivileged_group_lease_does_not_grant_root_authority():
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("isolated Linux root fixtures required")
    # /root cannot be traversed by a dropped service identity. /run's protected
    # ancestry supports an ephemeral, read-only-to-service test installation.
    with tempfile.TemporaryDirectory(prefix="knxoh-lease-test-", dir="/run") as directory:
        root = Path(directory)
        root.chmod(0o755)
        config = root / "config"
        config.mkdir(mode=0o755)
        lease = config / ".updater-mutation.lock"
        lease.touch()
        os.chown(lease, 0, 65534)
        lease.chmod(0o660)
        code = (
            "from pathlib import Path; from types import SimpleNamespace; "
            "from installer.update_core import maintenance as m; "
            f"p=SimpleNamespace(config_dir=Path({str(config)!r})); "
            "ctx=m.mutation_lease(p); ctx.__enter__(); ctx.__exit__(None,None,None); "
            "m.wait_for_quiescence(p, .01)"
        )

        def drop_privileges():
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)

        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, preexec_fn=drop_privileges
        )
        assert result.returncode != 0
        assert "PermissionError" in result.stderr
        assert "mutation_lease" not in result.stderr
        assert not (config / ".updater-maintenance.json").exists()


def test_body_validation_is_not_reclassified_as_maintenance(protected):
    from installer.update_core import maintenance as m

    with pytest.raises(ValueError, match="invalid user input"):
        with m.mutation_lease(protected):
            raise ValueError("invalid user input")


def test_failed_coordinator_retains_intent_for_recovery(protected):
    from installer.update_core import maintenance as m

    with pytest.raises(RuntimeError):
        with m.wait_for_quiescence(protected, 0.1):
            raise RuntimeError("rollback did not establish coherence")
    assert m.maintenance_requested(protected)
    with pytest.raises(m.MaintenanceError):
        with m.mutation_lease(protected):
            pytest.fail("failed recovery admitted writes")


def test_request_specific_intent_cleanup_refuses_unrelated_owner(protected):
    from installer.update_core import maintenance as m

    request_id = str(uuid4())
    marker = protected.config_dir / m.INTENT_NAME
    lease = protected.config_dir / m.LEASE_NAME
    identity = (lease.stat().st_dev, lease.stat().st_ino)
    with m.wait_for_quiescence(protected, 0.1, request_id=request_id):
        original = marker.read_bytes()
        with pytest.raises(m.MaintenanceError):
            m.clear_request_intent(protected, str(uuid4()))
        assert marker.read_bytes() == original
    assert not marker.exists()
    assert (lease.stat().st_dev, lease.stat().st_ino) == identity


def test_request_intent_absence_retry_fsyncs_parent_without_touching_lease(protected, monkeypatch):
    from installer.update_core import maintenance as m

    lease = protected.config_dir / m.LEASE_NAME
    identity = (lease.stat().st_dev, lease.stat().st_ino)
    synced = []
    sync = os.fsync

    def record(fd):
        synced.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return sync(fd)

    monkeypatch.setattr(os, "fsync", record)
    m.clear_request_intent(protected, str(uuid4()))
    assert protected.config_dir in synced
    assert (lease.stat().st_dev, lease.stat().st_ino) == identity


def test_health_is_session_free_and_source_version(monkeypatch):
    monkeypatch.setitem(app_module.cfg, "auth", {"enabled": True})
    monkeypatch.setattr(app_module, "_sessions", lambda: pytest.fail("session touched"))
    response = app_module.app.test_client().get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ready",
        "version": (Path(app_module.project_root) / "VERSION").read_text().strip(),
    }
    assert not response.headers.get("Set-Cookie")


def test_protected_install_missing_lease_not_dev(monkeypatch, tmp_path):
    from web_ui.backend import update_maintenance as facade

    paths = SimpleNamespace(config_dir=tmp_path, secrets_file=tmp_path / "secrets.env")
    monkeypatch.setenv("FLASK_ENV", "development")
    with pytest.raises(facade.MaintenanceError):
        with facade.mutation_lease(paths):
            pytest.fail("production bypassed")


def test_release_layout_without_external_environment_still_fails_closed(tmp_path):
    from web_ui.backend import update_maintenance as facade

    paths = SimpleNamespace(
        config_dir=tmp_path,
        secrets_file=None,
        project_root=tmp_path / "releases/1.0.0",
        install_dir=tmp_path,
    )
    with pytest.raises(facade.MaintenanceError):
        with facade.mutation_lease(paths):
            pytest.fail("versioned install treated as development")


def test_route_mutations_block_but_invalid_input_and_reads_survive(protected, monkeypatch):
    from installer.update_core import maintenance as m

    monkeypatch.setitem(app_module.cfg, "auth", {"enabled": False})
    paths = SimpleNamespace(config_dir=protected.config_dir, secrets_file=Path("external"))
    monkeypatch.setattr(app_module, "get_paths", lambda *args: paths)
    client = app_module.app.test_client()
    with m.wait_for_quiescence(protected, 0.1):
        for route, data in [
            ("/api/config", {"sibling": "preserved"}),
            ("/api/service/restart", {"service": "openhab.service"}),
            ("/api/job/abc/deploy", {}),
            ("/api/job/abc/rollback", {}),
        ]:
            response = client.post(route, json=data)
            assert response.status_code == 503, (route, response.get_json())
        assert client.delete("/api/job/abc").status_code == 503
        assert client.post("/api/config", json=[]).status_code == 400
        assert client.post("/api/service/restart", json={}).status_code == 400
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/version/log").status_code == 200


def test_jobs_hold_independent_leases_while_queued_and_on_failure(protected, monkeypatch, tmp_path):
    import threading

    from installer.update_core import maintenance as m
    from web_ui.backend import jobs

    paths = SimpleNamespace(config_dir=protected.config_dir, secrets_file=Path("external"))
    monkeypatch.setattr(jobs, "get_paths", lambda: paths)
    manager = jobs.JobManager({"jobs_dir": str(tmp_path), "backups_dir": str(tmp_path)})
    release = threading.Event()
    futures = []
    submit = manager.executor.submit

    def tracked_submit(*args):
        future = submit(*args)
        futures.append(future)
        return future

    monkeypatch.setattr(manager.executor, "submit", tracked_submit)

    def run(_job):
        release.wait(5)
        raise RuntimeError("worker failed before normal cleanup")

    monkeypatch.setattr(manager, "_run_job", run)
    try:
        for _ in range(3):
            manager.create_job("input.json", password="not-persisted")
        with pytest.raises(TimeoutError):
            m.wait_for_quiescence(protected, 0.01)
        # Queued submissions must also reject intent, even within this process.
        from installer.update_core import secure_fs

        secure_fs.atomic_write(protected.config_dir / m.INTENT_NAME, b"{}", 0, 0, 0o644)
        with pytest.raises(m.MaintenanceError):
            manager.create_job("blocked.json")
        m._clear_intent(protected)
    finally:
        release.set()
        manager.executor.shutdown(wait=True)
    with m.wait_for_quiescence(protected, 0.1):
        pass
    assert len(futures) == 3
    assert not manager._passwords


def test_background_service_operation_drains(protected, monkeypatch):
    import threading

    from installer.update_core import maintenance as m
    from web_ui.backend import service_updates as services

    paths = SimpleNamespace(config_dir=protected.config_dir, secrets_file=Path("external"))
    monkeypatch.setattr(services, "get_paths", lambda: paths, raising=False)
    monkeypatch.setattr(services.os.path, "isfile", lambda path: True)
    started, finish, done = threading.Event(), threading.Event(), threading.Event()
    service = services.ServiceUpdates()

    def run(*args):
        started.set()
        finish.wait(5)
        done.set()

    monkeypatch.setattr(service, "_run", run)
    try:
        assert service.start("refresh")[0]
        assert started.wait(2)
        with pytest.raises(TimeoutError):
            m.wait_for_quiescence(protected, 0.01)
    finally:
        finish.set()
        assert done.wait(2)


def test_queued_future_cancellation_releases_only_its_lease_and_password(
    protected, monkeypatch, tmp_path
):
    import threading

    from installer.update_core import maintenance as m
    from web_ui.backend import jobs

    paths = SimpleNamespace(config_dir=protected.config_dir, secrets_file=Path("external"))
    monkeypatch.setattr(jobs, "get_paths", lambda: paths)
    manager = jobs.JobManager({"jobs_dir": str(tmp_path), "backups_dir": str(tmp_path)})
    release = threading.Event()
    started = [threading.Event(), threading.Event()]
    futures = []
    submit = manager.executor.submit

    def tracked_submit(*args):
        future = submit(*args)
        futures.append(future)
        return future

    def run(job_id):
        index = 0 if not started[0].is_set() else 1
        started[index].set()
        assert release.wait(5)

    monkeypatch.setattr(manager.executor, "submit", tracked_submit)
    monkeypatch.setattr(manager, "_run_job", run)
    try:
        for event in started:
            manager.create_job("running.json", password="running-secret")
            assert event.wait(2)
        queued = manager.create_job("queued.json", password="queued-secret")
        assert futures[-1].cancel() and futures[-1].cancelled()
        assert queued["id"] not in manager._passwords
        assert len(manager._passwords) == 2
        # Cancelling one job must not release either still-running job's lease.
        with pytest.raises(TimeoutError):
            m.wait_for_quiescence(protected, 0.01)
    finally:
        release.set()
        manager.executor.shutdown(wait=True)
    assert not manager._passwords
    with m.wait_for_quiescence(protected, 0.1):
        pass


def test_auth_errors_not_masked_by_maintenance(protected, monkeypatch):
    from installer.update_core import maintenance as m

    monkeypatch.setitem(app_module.cfg, "auth", {"enabled": True, "password_hash": "configured"})
    with m.wait_for_quiescence(protected, 0.1):
        response = app_module.app.test_client().post("/api/config", json={"x": 1})
        assert response.status_code == 401


def test_csrf_errors_not_masked_by_maintenance(protected, monkeypatch, tmp_path):
    from installer.update_core import maintenance as m
    from web_ui.backend.session_store import SessionStore

    monkeypatch.setitem(app_module.cfg, "auth", {"enabled": True, "password_hash": "configured"})
    monkeypatch.setattr(app_module, "get_session_secret", lambda *args: b"k" * 32)
    store = SessionStore(str(tmp_path / "sessions.sqlite3"), b"k" * 32)
    monkeypatch.setattr(app_module, "_session_store", store)
    token, _csrf = store.create("operator", credential_version=app_module._credential_version())
    client = app_module.app.test_client()
    client.set_cookie("knx_session", token)
    with m.wait_for_quiescence(protected, 0.1):
        assert client.post("/api/config", json={"x": 1}).status_code == 403


def test_submission_failure_releases_lease(protected, monkeypatch, tmp_path):
    from installer.update_core import maintenance as m
    from web_ui.backend import jobs

    paths = SimpleNamespace(config_dir=protected.config_dir, secrets_file=Path("external"))
    monkeypatch.setattr(jobs, "get_paths", lambda: paths)
    manager = jobs.JobManager({"jobs_dir": str(tmp_path), "backups_dir": str(tmp_path)})
    manager.executor.shutdown(wait=True)
    with pytest.raises(RuntimeError):
        manager.create_job("input.json", password="secret")
    assert not manager._passwords
    assert not manager._jobs
    with m.wait_for_quiescence(protected, 0.1):
        pass


def test_each_shared_lease_has_independent_lifetime(protected):
    from installer.update_core import maintenance as m

    first, second = m.mutation_lease(protected), m.mutation_lease(protected)
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    try:
        with pytest.raises(TimeoutError):
            m.wait_for_quiescence(protected, 0.01)
    finally:
        second.__exit__(None, None, None)
    with m.wait_for_quiescence(protected, 0.1):
        pass


def test_health_rejects_stale_worker_and_gate(protected, monkeypatch):
    from web_ui.backend.update_maintenance import readiness_version

    release = protected.releases / "1.0.0"
    release.mkdir(parents=True)
    (release / "VERSION").write_text("1.0.0")
    protected.current.symlink_to(release)
    paths = SimpleNamespace(
        project_root=release,
        install_dir=protected.current.parent,
        config_dir=protected.config_dir,
        secrets_file=Path("external"),
    )
    assert readiness_version(paths) == "1.0.0"
    (protected.config_dir / ".updater-startup-gate.json").write_text("invalid")
    with pytest.raises(ValueError):
        readiness_version(paths)
    (protected.config_dir / ".updater-startup-gate.json").unlink()
    paths.project_root = protected.releases / "old"
    with pytest.raises((ValueError, OSError)):
        readiness_version(paths)
