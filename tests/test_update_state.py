"""Transaction state tests use private root-owned fixtures, never host policy."""

import json
import os
import stat
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from installer.update_core import state
from installer.update_core.protocol import Journal, Paths

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX protected filesystem")


@pytest.fixture
def paths():
    if os.geteuid() != 0:
        pytest.skip("requires isolated Linux root test process")
    with tempfile.TemporaryDirectory(prefix="knxoh-state-", dir="/root") as directory:
        root = Path(directory)
        (root / "releases").mkdir()
        (root / "releases/1.0.0").mkdir()
        (root / "releases/2.0.0").mkdir()
        (root / "current").symlink_to(root / "releases/1.0.0")
        (root / "config").mkdir(mode=0o755)
        yield Paths(root / "releases", root / "current", root / "config")


def journal(paths, **kwargs):
    return Journal(
        paths.releases / "2.0.0",
        paths.releases / "1.0.0",
        None,
        12345,
        request_id=str(uuid4()),
        **kwargs,
    )


def test_lock_excludes_nested_and_releases_on_failure(paths):
    lock = state.LifecycleLock(paths.config_dir / "lock")
    with pytest.raises(RuntimeError):
        with lock.acquire():
            with pytest.raises(BlockingIOError):
                with state.LifecycleLock(paths.config_dir / "lock").acquire():
                    pytest.fail("second owner entered")
            raise RuntimeError("interruption")
    with lock.acquire():
        pass


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "owner", "writable"])
def test_unsafe_lock_refused(paths, kind):
    path = paths.config_dir / "lock"
    path.write_bytes(b"")
    if kind == "symlink":
        path.unlink()
        path.symlink_to(paths.config_dir / "other")
    elif kind == "hardlink":
        os.link(path, paths.config_dir / "other")
    elif kind == "owner":
        os.chown(path, 12345, 12345)
    else:
        path.chmod(0o666)
    with pytest.raises((OSError, ValueError)):
        with state.LifecycleLock(path).acquire():
            pytest.fail("unsafe lock entered")


def test_lock_accepts_root_sticky_lock_directory_but_not_plain_writable_parent(paths):
    # /run/lock is normally root:root 1777 on Debian. Sticky semantics protect
    # a root-owned lock leaf from other users; plain 0777 offers no such safety.
    directory = paths.config_dir / "locks"
    directory.mkdir()
    directory.chmod(0o1777)
    lock = state.LifecycleLock(directory / "lock")
    with lock.acquire():
        with pytest.raises(BlockingIOError):
            with lock.acquire():
                pytest.fail("second owner")
    directory.chmod(0o777)
    with pytest.raises(ValueError):
        with lock.acquire():
            pytest.fail("unsafe parent")


def test_journal_roundtrip_and_replay_survives_next_transaction(paths):
    store = state.StateStore(paths)
    assert store.load() is None
    first = journal(paths)
    store.save(first)
    assert store.load() == first
    with pytest.raises(ValueError):
        store.save(journal(paths))  # active transaction cannot be replaced
    store.save(replace(first, phase="committed"))
    second = journal(paths)
    store.save(second)
    store.save(replace(second, phase="rolled-back"))
    with pytest.raises(ValueError):
        store.save(first)
    assert stat.S_IMODE(store.journal_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.journal_path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": 2},
        {"phase": "guess"},
        {"phase": []},
        {"candidate": "/etc"},
        {"candidate": 12},
        {"prior_target": "/etc"},
        {"snapshot_allowlist": ["secrets.env"]},
        {"service_states": {"evil.service": "active"}},
        {"candidate_created": 1},
        {"request_id": "not-a-uuid"},
        {"unexpected": True},
    ],
)
def test_corrupt_future_or_unallowlisted_journal_blocks(paths, change):
    store = state.StateStore(paths)
    store.save(journal(paths))
    value = json.loads(store.journal_path.read_bytes())
    value.update(change)
    store.journal_path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        store.load()


@pytest.mark.parametrize("present", [True, False])
def test_snapshot_restores_bytes_metadata_and_absence_only(paths, present):
    store = state.StateStore(paths)
    original = paths.config_dir / "config.json"
    unrelated = paths.config_dir / "secrets.env"
    unrelated.write_bytes(b"secret unchanged")
    if present:
        original.write_bytes(b'{"key":"\xc3\xa4"}\r\n')
        os.chown(original, 0, 12345)
        original.chmod(0o640)
    first = journal(paths)
    store.save(first)
    store.snapshot_config()
    original.write_bytes(b"new")
    original.chmod(0o600)
    store.restore_config()
    store.restore_config()  # idempotent
    if present:
        assert original.read_bytes() == b'{"key":"\xc3\xa4"}\r\n'
        info = original.stat()
        assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 12345, 0o640)
    else:
        assert not original.exists()
    assert unrelated.read_bytes() == b"secret unchanged"


def test_snapshot_cannot_be_overwritten_or_reused_for_another_request(paths):
    store = state.StateStore(paths)
    config = paths.config_dir / "config.json"
    config.write_bytes(b"old")
    first = journal(paths)
    store.save(first)
    store.snapshot_config()
    config.write_bytes(b"new")
    with pytest.raises(ValueError):
        store.snapshot_config()
    store.save(replace(first, phase="committed"))
    store.save(journal(paths))
    with pytest.raises((ValueError, FileNotFoundError)):
        store.restore_config()
    assert config.read_bytes() == b"new"


@pytest.mark.parametrize("boundary", ["before", "after"])
@pytest.mark.parametrize("operation", ["journal", "snapshot", "restore", "gate", "status"])
def test_atomic_write_interruption_leaves_only_complete_records(
    paths, monkeypatch, boundary, operation
):
    store = state.StateStore(paths)
    config = paths.config_dir / "config.json"
    config.write_bytes(b"original")
    first = journal(paths)
    store.save(first)
    if operation == "restore":
        store.snapshot_config()
        config.write_bytes(b"changed")
    write = state.fs.atomic_write

    def interrupted(*args, **kwargs):
        if boundary == "after":
            write(*args, **kwargs)
        raise OSError("injected crash")

    with monkeypatch.context() as patch:
        patch.setattr(state.fs, "atomic_write", interrupted)
        with pytest.raises(OSError):
            if operation == "journal":
                store.save(replace(first, phase="preparing"))
            elif operation == "snapshot":
                store.snapshot_config()
            elif operation == "restore":
                store.restore_config()
            elif operation == "gate":
                state.write_gate(paths, "deny", None, None)
            else:
                store.publish_status("preparing", "Preparing release")
    assert store.load().phase in ("claimed", "preparing")
    assert config.read_bytes() in (b"original", b"changed")
    if operation == "snapshot":
        if boundary == "after":
            store.restore_config()
        else:
            with pytest.raises(FileNotFoundError):
                store.restore_config()


def test_public_status_is_bounded_sanitized_and_not_private_state(paths):
    store = state.StateStore(paths)
    store.save(journal(paths))
    store.publish_status("preparing", "Preparing release")
    public = paths.config_dir / ".updater-status.json"
    assert json.loads(public.read_bytes()) == {
        "format_version": 1,
        "phase": "preparing",
        "message": "Preparing release",
    }
    assert stat.S_IMODE(public.stat().st_mode) == 0o644
    assert stat.S_IMODE((paths.config_dir / ".updater-log.txt").stat().st_mode) == 0o644
    with pytest.raises(ValueError):
        store.publish_status("preparing", "secret\nforged log")
    with pytest.raises(ValueError):
        store.publish_status("preparing", "x" * 1025)


def test_candidate_owner_and_service_provenance_cannot_change(paths):
    store = state.StateStore(paths)
    first = journal(paths, service_states={"knxohui.service": {"active": True, "enabled": False}})
    store.save(first)
    with pytest.raises(ValueError):
        store.save(replace(first, candidate_uid=54321))
    with pytest.raises(ValueError):
        store.save(replace(first, service_states={}))


@pytest.mark.parametrize("kind", ["journal", "snapshot", "config", "root"])
def test_state_refuses_symlink_destinations(paths, kind):
    store = state.StateStore(paths)
    first = journal(paths)
    store.save(first)
    config = paths.config_dir / "config.json"
    config.write_bytes(b"original")
    keep = paths.config_dir / "unrelated"
    keep.write_bytes(b"unchanged")
    if kind == "journal":
        store.journal_path.unlink()
        store.journal_path.symlink_to(keep)

        def operation():
            store.save(first)

    elif kind == "snapshot":
        (store.root / ("snapshot-" + first.request_id + ".json")).symlink_to(keep)
        operation = store.snapshot_config
    elif kind == "root":
        store.journal_path.unlink()
        store.root.rmdir()
        store.root.symlink_to(paths.config_dir)
        operation = store.load
    else:
        store.snapshot_config()
        config.unlink()
        config.symlink_to(keep)
        operation = store.restore_config
    with pytest.raises((ValueError, OSError)):
        operation()
    assert keep.read_bytes() == b"unchanged"


@pytest.mark.parametrize("boundary", ["before", "after"])
@pytest.mark.parametrize("write_number", [1, 2])
def test_restore_and_publication_each_durable_write_is_crash_safe(
    paths, monkeypatch, boundary, write_number
):
    store = state.StateStore(paths)
    store.save(journal(paths))
    config = paths.config_dir / "config.json"
    config.write_bytes(b"original")
    store.snapshot_config()
    config.write_bytes(b"changed")
    write = state.fs.atomic_write
    for operation in (store.restore_config, lambda: store.publish_status("preparing", "Preparing")):
        calls = 0

        def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == write_number and boundary == "before":
                raise OSError("before write")
            write(*args, **kwargs)
            if calls == write_number:
                raise OSError("after write")

        with monkeypatch.context() as patch:
            patch.setattr(state.fs, "atomic_write", interrupted)
            with pytest.raises(OSError):
                operation()
        assert config.read_bytes() in (b"original", b"changed")
        assert store.load().phase == "claimed"
    # A retry of restoration always converges, and the deny gate remains set.
    store.restore_config()
    assert config.read_bytes() == b"original"
    assert (
        json.loads((paths.config_dir / ".updater-startup-gate.json").read_bytes())["mode"] == "deny"
    )


@pytest.mark.parametrize("sync_number", [1, 2, 3, 4])
@pytest.mark.parametrize("boundary", ["before", "after"])
def test_restore_sync_failures_never_publish_unprotected_config(
    paths, monkeypatch, sync_number, boundary
):
    store = state.StateStore(paths)
    store.save(journal(paths))
    config = paths.config_dir / "config.json"
    config.write_bytes(b"original")
    store.snapshot_config()
    config.write_bytes(b"changed")
    sync = os.fsync
    calls = 0

    def interrupted(fd):
        nonlocal calls
        calls += 1
        if calls == sync_number and boundary == "before":
            raise OSError("before fsync")
        sync(fd)
        if calls == sync_number:
            raise OSError("after fsync")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", interrupted)
        with pytest.raises(OSError):
            store.restore_config()
    if sync_number <= 2:
        assert config.read_bytes() == b"changed"
    else:
        assert (
            json.loads((paths.config_dir / ".updater-startup-gate.json").read_bytes())["mode"]
            == "deny"
        )
        assert config.read_bytes() in (b"original", b"changed")
    store.restore_config()
    assert config.read_bytes() == b"original"
