"""Crash at durable intent/effect boundaries; boot/offline never start a service."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from installer.update_core.state import StateStore, check_start_allowed
from tests.test_release_updater import assert_sentinels, installation  # noqa: F401


class Crash(BaseException):
    pass


def recover_boot(updater, adapter):
    # Explicit simulated reboot precondition, not a coordinator service effect.
    adapter.active = dict.fromkeys(adapter.active, False)
    return updater.recover("boot")


def test_recovery_interface_modes():
    from installer.update_core.transaction import ReleaseUpdater

    assert callable(ReleaseUpdater.recover)


@pytest.mark.parametrize("boundary", range(1, 65))
def test_crash_boundary_recovers_coherent_pair_without_start(installation, monkeypatch, boundary):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation
    original = (paths.config_dir / "config.json").read_bytes()
    count = 0
    real_boundary = transaction.ReleaseUpdater._boundary

    def crash(self, label):
        nonlocal count
        count += 1
        if label in ("effect:config", "effect:activate"):
            assert not check_start_allowed(paths, "ui")
            assert not check_start_allowed(paths, "cleanup")
        elif label == "effect:gate-permit":
            assert check_start_allowed(paths, "ui")
            assert not check_start_allowed(paths, "cleanup")
        if count == boundary:
            raise Crash(label)
        real_boundary(self, label)

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    try:
        result = updater.run()
    except Crash:
        result = None
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", real_boundary)
    if result is not None:
        assert result.status == "updated", result
        return
    before = StateStore(paths).load()
    adapter.events.clear()
    result = recover_boot(updater, adapter)
    assert result.status in ("recovered", "clean"), (boundary, result)
    assert not any(isinstance(event, tuple) and event[0] == "start" for event in adapter.events)
    if before is not None and before.phase == "committed":
        assert paths.current.resolve() == paths.releases / "2.0.0"
    else:
        assert paths.current.resolve() == paths.releases / "1.0.0"
        assert (paths.config_dir / "config.json").read_bytes() == original
    assert check_start_allowed(paths, "ui")
    assert check_start_allowed(paths, "cleanup")
    assert_sentinels(paths)
    assert recover_boot(updater, adapter).status in ("recovered", "clean")


def test_recovered_awaiting_start_requires_previous_health(installation, monkeypatch):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation

    def crash(self, label):
        if label == "effect:activate":
            raise Crash()

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    with pytest.raises(Crash):
        updater.run()
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    assert recover_boot(updater, adapter).status == "recovered"
    assert StateStore(paths).load().phase == "recovered-awaiting-start"
    assert updater.run().status == "blocked"
    adapter.active["knxohui.service"] = True
    # The old ID is replayed, not accepted; restored health permits terminalization only.
    assert updater.run().status == "blocked"
    assert StateStore(paths).load().phase == "rolled-back"


@pytest.mark.parametrize("fault", ["future", "target", "missing-prior", "snapshot"])
def test_corrupt_recovery_retains_evidence(installation, monkeypatch, fault):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation

    def crash(self, label):
        if label == "effect:activate":
            raise Crash()

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    with pytest.raises(Crash):
        updater.run()
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    store = StateStore(paths)
    if fault == "future":
        value = json.loads(store.journal_path.read_bytes())
        value["format_version"] = 99
        store.journal_path.write_text(json.dumps(value))
    elif fault == "target":
        (paths.releases / "3.0.0").mkdir()
        paths.current.unlink()
        paths.current.symlink_to(paths.releases / "3.0.0")
    elif fault == "missing-prior":
        (paths.releases / "1.0.0/VERSION").unlink()
        (paths.releases / "1.0.0").rmdir()
    else:
        (store.root / ("snapshot-" + store.load().request_id + ".json")).write_bytes(b"bad")
    evidence = store.journal_path.read_bytes()
    assert recover_boot(updater, adapter).status == "blocked"
    assert store.journal_path.exists()
    if fault == "future":
        assert store.journal_path.read_bytes() == evidence
    assert not check_start_allowed(paths, "cleanup")


def test_offline_refuses_active_writers_without_mutation(installation):
    updater, paths, adapter, _ = installation
    assert updater.recover("offline").status == "blocked"
    assert not adapter.events


def test_clean_state_refuses_uncommitted_and_unknown_journal(installation):
    from installer.update_core.protocol import Journal

    updater, paths, adapter, request_id = installation
    assert updater.check_clean_state().status == "clean"
    StateStore(paths).save(
        Journal(None, paths.releases / "1.0.0", None, 65534, request_id=request_id)
    )
    assert updater.check_clean_state().status == "blocked"


def test_standalone_entrypoint_trusted_bundle_only(installation):
    updater, paths, adapter, _ = installation
    source = Path(__file__).resolve().parents[1] / "installer"
    bundle = paths.releases.parent.parent / "libexec"
    bundle.mkdir()
    for name in ("update_release.py", "update_start_guard.py"):
        shutil.copyfile(source / name, bundle / name)
    shutil.copytree(
        source / "update_core",
        bundle / "update_core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in bundle.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    marker = paths.config_dir / "untrusted-import"
    poison = paths.releases / "1.0.0"
    (poison / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'w').write('bad')")
    (poison / "transaction.py").write_text("raise RuntimeError('untrusted')")
    command = ["/usr/bin/python3", "-I", str(bundle / "update_release.py"), "--help"]
    result = subprocess.run(
        command,
        cwd=poison,
        env={"PYTHONPATH": str(poison), "PATH": "/evil"},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert b"--recover-offline" in result.stdout and b"--check-clean-state" in result.stdout
    assert not marker.exists()
    assert subprocess.run([command[0], *command[2:]], capture_output=True).returncode != 0
    (bundle / "update_core/transaction.py").chmod(0o666)
    assert subprocess.run(command, capture_output=True).returncode != 0


def test_recovery_holds_exclusive_mutation_lease(installation, monkeypatch):
    from installer.update_core import maintenance, transaction

    updater, paths, adapter, request_id = installation

    def crash(self, label):
        if label == "effect:activate":
            raise Crash()

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    with pytest.raises(Crash):
        updater.run()
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    original_restore = StateStore.restore_config

    def restore(store):
        with pytest.raises(maintenance.MaintenanceError):
            with maintenance.mutation_lease(paths):
                pytest.fail("mutation admitted during recovery")
        return original_restore(store)

    monkeypatch.setattr(StateStore, "restore_config", restore)
    assert recover_boot(updater, adapter).status == "recovered"


@pytest.mark.parametrize("boundary", range(1, 76))
def test_crash_during_rollback_can_be_recovered_offline(installation, monkeypatch, boundary):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation
    original = (paths.config_dir / "config.json").read_bytes()
    adapter.fail = "health"
    count = 0

    def crash(self, label):
        nonlocal count
        count += 1
        if count == boundary:
            raise Crash(label)

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    try:
        result = updater.run()
    except Crash:
        result = None
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    if result is not None:
        assert result.status == "failed" and result.rollback_status == "succeeded"
    adapter.active = dict.fromkeys(adapter.active, False)
    adapter.events.clear()
    result = updater.recover("offline")
    assert result.status in ("recovered", "clean"), (boundary, result)
    assert not any(isinstance(event, tuple) and event[0] == "start" for event in adapter.events)
    assert paths.current.resolve() == paths.releases / "1.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == original
    assert_sentinels(paths)


def test_failed_pre_snapshot_stop_is_recoverable_without_guessing_snapshot(installation):
    updater, paths, adapter, _ = installation
    service = adapter.service
    failed = False

    def fail_stop(action, name):
        nonlocal failed
        if action == "stop" and not failed:
            failed = True
            raise RuntimeError("stop failed")
        if action == "start":
            raise RuntimeError("rollback restart failed")
        return service(action, name)

    adapter.service = fail_stop
    result = updater.run()
    assert result.rollback_status.startswith("failed:"), result
    assert updater.run().status == "blocked"
    adapter.service = service
    adapter.active = dict.fromkeys(adapter.active, False)
    assert updater.recover("offline").status == "recovered"


def test_recovered_journal_rejects_stale_old_http_on_wrong_current(installation, monkeypatch):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation

    def crash(self, label):
        if label == "effect:activate":
            raise Crash()

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    with pytest.raises(Crash):
        updater.run()
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    assert recover_boot(updater, adapter).status == "recovered"
    paths.current.unlink()
    paths.current.symlink_to(paths.releases / "2.0.0")
    adapter.active["knxohui.service"] = True
    updater.http = lambda *args: {"status": "ready", "version": "1.0.0"}
    assert updater.run().status == "blocked"
    assert StateStore(paths).load().phase == "recovered-awaiting-start"


@pytest.mark.parametrize("boundary", range(1, 51))
def test_interrupted_boot_recovery_converges_without_ui_start(installation, monkeypatch, boundary):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation
    original = (paths.config_dir / "config.json").read_bytes()

    def initial(self, label):
        if label == "effect:activate":
            raise Crash()

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", initial)
    with pytest.raises(Crash):
        updater.run()
    count = 0

    def crash(self, label):
        nonlocal count
        count += 1
        if count == boundary:
            raise Crash(label)

    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", crash)
    adapter.events.clear()
    try:
        assert recover_boot(updater, adapter).status == "recovered"
    except Crash:
        pass
    monkeypatch.setattr(transaction.ReleaseUpdater, "_boundary", lambda *args: None)
    assert recover_boot(updater, adapter).status == "recovered"
    assert not any(isinstance(event, tuple) and event[0] == "start" for event in adapter.events)
    assert paths.current.resolve().name == "1.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == original


@pytest.mark.parametrize("failure, maximum", [(None, 64), ("health", 75)])
def test_crash_matrix_covers_all_run_boundaries(installation, monkeypatch, failure, maximum):
    from installer.update_core import transaction

    updater, paths, adapter, _ = installation
    labels = []
    adapter.fail = failure
    monkeypatch.setattr(
        transaction.ReleaseUpdater, "_boundary", lambda self, label: labels.append(label)
    )
    updater.run()
    assert len(labels) <= maximum, (len(labels), labels)
    assert labels[-1] == "effect:maintenance-release"
