"""Trusted administrator history transitions; only temporary protected files/fakes."""

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def history(monkeypatch):
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("temporary Linux root-owned state fixture")
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Journal, Paths
    from installer.update_core.state import LifecycleLock, StateStore

    with tempfile.TemporaryDirectory(prefix="knxoh-history-", dir="/run") as tmp:
        root = Path(tmp)
        paths = Paths(
            root / "app/releases",
            root / "app/current",
            root / "config",
            root / "data",
            root / "backup",
        )
        for path in (paths.releases, paths.config_dir, paths.data_dir, paths.backup_dir):
            path.mkdir(parents=True)
        prior, current = paths.releases / "1.0.0", paths.releases / "1.1.0"
        prior.mkdir()
        current.mkdir()
        paths.current.symlink_to(current)
        (paths.config_dir / "config.json").write_bytes(b'{"preserve":true}')
        (paths.data_dir / "jobs.json").write_bytes(b"unrelated-runtime")
        contract = root / "paths.env"
        contract.write_text(
            "".join(
                f'{key}="{value}"\n'
                for key, value in zip(
                    ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                    (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir),
                )
            )
        )
        monkeypatch.setattr(admin, "PATHS_FILE", contract)
        lock = LifecycleLock(root / "host.lock")
        monkeypatch.setattr(admin, "LifecycleLock", lambda: lock)
        store = StateStore(paths)
        journal = Journal(
            current,
            prior,
            (current.stat().st_dev, current.stat().st_ino),
            0,
            candidate_created=True,
            candidate_published=True,
            request_id=str(uuid4()),
        )
        with lock.acquire():
            store.save(journal)
            journal = replace(journal, phase="committed")
            store.save(journal)
        snapshot = store.root / ("snapshot-" + journal.request_id + ".json")
        snapshot.write_bytes(b"original-recovery-evidence")
        yield SimpleNamespace(
            root=root,
            paths=paths,
            store=store,
            journal=journal,
            lock=lock,
            contract=contract,
            snapshot=snapshot,
        )


@pytest.mark.parametrize("options", [["--repair"], [], ["--repair", "--activate-existing"]])
def test_committed_history_allows_verified_admin_install_and_repeat(history, monkeypatch, options):
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Journal

    h = history
    original = h.store.journal_path.read_bytes()
    calls = []

    def shell(argv, **kwargs):
        calls.append(argv)
        with h.lock.inherited(int(kwargs["env"]["KNXOH_LIFECYCLE_FD"])) as fd:
            with admin.installer_lease(h.paths, h.contract, inherited=fd):
                previous = h.paths.current.resolve()
                target = previous
                if not options or "--activate-existing" in options:
                    target = h.paths.releases / "2.0.0"
                    target.mkdir(exist_ok=True)
                    h.paths.current.unlink()
                    h.paths.current.symlink_to(target)
                value = {
                    key: False
                    for key in (
                        "ui_start",
                        "ui_enable",
                        "cleanup_start",
                        "cleanup_enable",
                        "ui_was_active",
                        "ui_was_enabled",
                        "cleanup_service_was_active",
                        "cleanup_timer_was_active",
                        "cleanup_timer_was_enabled",
                    )
                }
                value.update(
                    mode="repair" if options else "install",
                    release=str(target),
                    previous=str(previous),
                    snapshot_file="",
                    release_was_incomplete=False,
                )
                Path(kwargs["env"]["KNXOH_BOOTSTRAP_OUTCOME"]).write_text(json.dumps(value))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(admin.subprocess, "run", shell)
    monkeypatch.setattr(admin, "_run", lambda argv: None)  # no live services or migration execution
    assert (
        admin.execute_setup(
            Path(__file__).resolve().parents[1] / "installer", h.paths, h.contract, options
        )
        == 0
    )
    assert (
        admin.execute_setup(
            Path(__file__).resolve().parents[1] / "installer", h.paths, h.contract, options
        )
        == 0
    )
    assert len(calls) == 2
    assert h.store.load() is None
    assert h.store._read()[1] == [h.journal.request_id]
    assert (h.store.root / ("terminal-" + h.journal.request_id + ".json")).read_bytes() == original
    assert h.snapshot.read_bytes() == b"original-recovery-evidence"
    assert (h.paths.data_dir / "jobs.json").read_bytes() == b"unrelated-runtime"
    with h.lock.acquire():
        replay = Journal(None, h.paths.current.resolve(), None, 0, request_id=h.journal.request_id)
        with pytest.raises(ValueError, match="replay"):
            h.store.save(replay)
        fresh = replace(replay, request_id=str(uuid4()))
        h.store.save(fresh)
    assert h.store._read()[1] == [h.journal.request_id, fresh.request_id]
    with h.lock.acquire():
        h.store.save(replace(fresh, phase="rolled-back"))
        h.store.archive_terminal_for_admin()
    assert h.store._read()[1] == [h.journal.request_id, fresh.request_id]
    assert len(list(h.store.root.glob("terminal-*"))) == 2


@pytest.mark.parametrize(
    "leaf,after",
    [("archive", False), ("archive", True), ("checkpoint", False), ("checkpoint", True)],
)
def test_history_archive_interruption_retains_ledger_and_evidence(
    history, monkeypatch, leaf, after
):
    from installer.update_core import secure_fs as fs

    h = history
    original = h.store.journal_path.read_bytes()
    real = fs.atomic_write

    def fault(path, *args, **kwargs):
        chosen = (
            path.name.startswith("terminal-") if leaf == "archive" else path.name == "journal.json"
        )
        if chosen and not after:
            raise OSError("fixture before atomic write")
        real(path, *args, **kwargs)
        if chosen:
            raise OSError("fixture after atomic write / directory fsync boundary")

    with h.lock.acquire():
        with monkeypatch.context() as patch:
            patch.setattr(fs, "atomic_write", fault)
            with pytest.raises(OSError):
                h.store.archive_terminal_for_admin()
        assert h.store._read()[1] == [h.journal.request_id]
        h.store.archive_terminal_for_admin()
        h.store.archive_terminal_for_admin()  # durable retry, including an already visible checkpoint
    assert h.store.load() is None
    assert (h.store.root / ("terminal-" + h.journal.request_id + ".json")).read_bytes() == original
    assert h.snapshot.read_bytes() == b"original-recovery-evidence"
    assert h.paths.current.resolve() == h.journal.candidate
    from installer.update_core.state import _decode_record

    # Old journal grammar must reject, not interpret the checkpoint as fresh
    # state during a power loss before administrator bundle replacement.
    with pytest.raises(ValueError):
        _decode_record(json.loads(h.store.journal_path.read_bytes()), h.paths)


@pytest.mark.parametrize("stage", ["before-shell", "during-install"])
def test_interrupted_admin_envelope_keeps_terminal_history_detached(history, monkeypatch, stage):
    from installer import update_bootstrap as admin
    from installer.update_core.state import check_start_allowed

    h = history

    def crash(argv, **kwargs):
        if stage == "during-install":
            target = h.paths.releases / "2.0.0"
            target.mkdir()
            (target / ".install-incomplete").write_bytes(b"")
            h.paths.current.unlink()
            h.paths.current.symlink_to(target)
        raise KeyboardInterrupt("fixture power loss")

    monkeypatch.setattr(admin.subprocess, "run", crash)
    with pytest.raises(KeyboardInterrupt):
        admin.execute_setup(
            Path(__file__).resolve().parents[1] / "installer", h.paths, h.contract, []
        )
    admin.check_clean_before_install(h.paths)  # never a stale terminal/current mismatch
    assert h.store.load() is None
    assert h.store._read()[1] == [h.journal.request_id]
    assert h.snapshot.read_bytes() == b"original-recovery-evidence"
    if stage == "during-install":
        assert not check_start_allowed(h.paths, "ui")


@pytest.mark.parametrize("bad", ["future", "extra", "missing", "tampered"])
def test_checkpoint_and_archive_corruption_fail_closed(history, bad):
    h = history
    with h.lock.acquire():
        h.store.archive_terminal_for_admin()
    value = json.loads(h.store.journal_path.read_bytes())
    archive = h.store.root / ("terminal-" + h.journal.request_id + ".json")
    if bad == "future":
        value["admin_history_version"] = 999
    if bad == "extra":
        value["destination"] = "/root/elsewhere"
    if bad in ("future", "extra"):
        h.store.journal_path.write_text(json.dumps(value))
    if bad == "missing":
        archive.unlink()
    if bad == "tampered":
        archive.write_bytes(archive.read_bytes() + b" ")
    before = h.store.journal_path.read_bytes()
    with pytest.raises((ValueError, OSError)):
        h.store.load()
    assert h.store.journal_path.read_bytes() == before


@pytest.mark.parametrize("bad", ["pending", "future", "corrupt", "mismatch", "gate"])
def test_admin_archive_does_not_relax_refusal_rules(history, bad):
    h = history
    value = json.loads(h.store.journal_path.read_bytes())
    if bad == "pending":
        value["phase"] = "checking"
    if bad == "future":
        value["format_version"] = 999
    if bad in ("pending", "future"):
        h.store.journal_path.write_text(json.dumps(value))
    if bad == "corrupt":
        h.store.journal_path.write_bytes(b"not-json")
    if bad == "mismatch":
        h.paths.current.unlink()
        h.paths.current.symlink_to(h.journal.prior_target)
    if bad == "gate":
        (h.paths.config_dir / ".updater-startup-gate.json").write_bytes(b"deny")
    before = h.store.journal_path.read_bytes()
    with h.lock.acquire():
        with pytest.raises((ValueError, OSError)):
            h.store.archive_terminal_for_admin()
    assert h.store.journal_path.read_bytes() == before
    assert not list(h.store.root.glob("terminal-*"))
