"""Real POSIX regressions; syscall doubles only inject otherwise nondeterministic faults."""

import os
import stat
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from installer.update_core import secure_fs
from installer.update_core.protocol import Journal, Paths

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX no-follow directory FDs")


@pytest.fixture
def tree():
    if os.geteuid() != 0:
        pytest.skip("ownership boundary requires isolated Linux root test process")
    # /tmp is intentionally rejected as a writable ancestor. Use root's private home.
    with tempfile.TemporaryDirectory(prefix="knxoh-secure-fs-", dir="/root") as directory:
        root = Path(directory)
        keep = root / "unrelated"
        keep.write_bytes(b"untouched")
        yield root
        assert keep.read_bytes() == b"untouched"


def test_read_regular_bounded_and_no_follow(tree):
    path = tree / "input"
    path.write_bytes(b"abc")
    assert secure_fs.read_regular(path, 3) == b"abc"
    with pytest.raises(ValueError):
        secure_fs.read_regular(path, 2)
    (tree / "link").symlink_to(path)
    with pytest.raises((ValueError, OSError)):
        secure_fs.read_regular(tree / "link", 10)


@pytest.mark.parametrize("operation", ["read", "write", "freeze"])
def test_symlink_and_writable_ancestors_rejected(tree, operation):
    directory = tree / "directory"
    directory.mkdir()
    path = directory / "file"
    path.write_bytes(b"old")
    link = tree / "alias"
    link.symlink_to(directory, target_is_directory=True)

    def run(target):
        if operation == "read":
            secure_fs.read_regular(target / "file", 20)
        elif operation == "write":
            secure_fs.atomic_write(target / "file", b"new", 0, 0, 0o640)
        else:
            secure_fs.freeze_tree(target / "file", 0)

    with pytest.raises((ValueError, OSError)):
        run(link)
    directory.chmod(0o777)
    with pytest.raises((ValueError, OSError)):
        run(directory)
    assert path.read_bytes() == b"old"


@pytest.mark.parametrize("kind", ["hardlink", "fifo", "setid", "owner"])
def test_unsafe_files_rejected_without_replacing_them(tree, kind):
    path = tree / "file"
    path.write_bytes(b"old")
    if kind == "hardlink":
        os.link(path, tree / "second")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif kind == "setid":
        path.chmod(0o4644)
    else:
        os.chown(path, 12345, 12345)
    for run in (
        lambda: secure_fs.read_regular(path, 20),
        lambda: secure_fs.atomic_write(path, b"new", 0, 0, 0o640),
    ):
        with pytest.raises((ValueError, OSError)):
            run()
    if kind != "fifo":
        assert path.read_bytes() == b"old"


def test_atomic_write_preserves_requested_metadata_and_syncs(tree, monkeypatch):
    path = tree / "config"
    path.write_bytes(b"old")
    write = os.write
    fsync = os.fsync
    synced = []

    def short_write(fd, data):
        return write(fd, data[:2])

    def sync(fd):
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        fsync(fd)

    monkeypatch.setattr(os, "write", short_write)
    monkeypatch.setattr(os, "fsync", sync)
    secure_fs.atomic_write(path, b"complete", 0, 12345, 0o640)
    assert path.read_bytes() == b"complete"
    info = path.stat()
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 12345, 0o640)
    assert synced == [False, True]
    assert sorted(p.name for p in tree.iterdir()) == ["config", "unrelated"]


def test_zero_write_keeps_original_and_cleans_temp(tree, monkeypatch):
    path = tree / "config"
    path.write_bytes(b"old")
    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(OSError):
        secure_fs.atomic_write(path, b"new", 0, 0, 0o600)
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tree.iterdir()) == ["config", "unrelated"]


def test_atomic_write_new_file_and_unsafe_requested_metadata(tree):
    path = tree / "new"
    for uid, mode in [(12345, 0o600), (0, 0o666), (0, 0o4600)]:
        with pytest.raises(ValueError):
            secure_fs.atomic_write(path, b"new", uid, 0, mode)
        assert not path.exists()
    secure_fs.atomic_write(path, b"new", 0, 0, 0o600)
    assert secure_fs.read_regular(path, 3) == b"new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_write_fsync_failure_keeps_original(tree, monkeypatch):
    path = tree / "config"
    path.write_bytes(b"old")

    def fail(fd):
        raise OSError("injected disk failure")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        secure_fs.atomic_write(path, b"new", 0, 0, 0o600)
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tree.iterdir()) == ["config", "unrelated"]


@pytest.mark.parametrize("ignored", ["fchown", "fchmod"])
def test_atomic_write_refuses_filesystem_ignoring_metadata_changes(tree, monkeypatch, ignored):
    path = tree / "config"
    path.write_bytes(b"old")
    monkeypatch.setattr(os, ignored, lambda *args: None)
    with pytest.raises((ValueError, OSError)):
        secure_fs.atomic_write(path, b"new", 0, 12345, 0o640)
    assert path.read_bytes() == b"old"


def test_disappearing_existing_destination_is_not_treated_as_new(tree, monkeypatch):
    path = tree / "file"
    path.write_bytes(b"old")
    open_fd = os.open

    def disappear(name, flags, *args, **kwargs):
        if name == "file":
            path.rename(tree / "saved")
        return open_fd(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", disappear)
    with pytest.raises((ValueError, OSError)):
        secure_fs.atomic_write(path, b"new", 0, 0, 0o600)
    assert not path.exists()
    assert (tree / "saved").read_bytes() == b"old"


@pytest.mark.parametrize("operation", ["read", "write"])
def test_raced_file_entry_rejected(tree, monkeypatch, operation):
    path = tree / "file"
    path.write_bytes(b"old")
    open_fd = os.open
    raced = False

    def open_race(name, flags, *args, **kwargs):
        nonlocal raced
        if name == "file" and not raced:
            raced = True
            path.rename(tree / "saved")
            path.write_bytes(b"replacement")
        return open_fd(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_race)
    with pytest.raises((ValueError, OSError)):
        if operation == "read":
            secure_fs.read_regular(path, 20)
        else:
            secure_fs.atomic_write(path, b"new", 0, 0, 0o600)
    assert path.read_bytes() == b"replacement"
    assert (tree / "saved").read_bytes() == b"old"


def candidate(tree):
    releases = tree / "releases"
    releases.mkdir()
    prior = releases / "1.0.0"
    prior.mkdir()
    current = tree / "current"
    current.symlink_to(prior)
    root = releases / "2.0.0"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin" / "run").write_bytes(b"executable")
    (root / "bin" / "run").chmod(0o750)
    info = root.stat()
    return Paths(releases, current), Journal(
        candidate=root,
        prior_target=prior,
        candidate_identity=(info.st_dev, info.st_ino),
        candidate_uid=0,
        candidate_created=True,
        candidate_published=False,
    )


def test_freeze_transfers_ownership_only_after_complete_validation(tree):
    paths, journal = candidate(tree)
    root = journal.candidate
    for path in [root / "bin" / "run", root / "bin", root]:
        os.chown(path, 12345, 12345)
    secure_fs.freeze_tree(root, 12345)
    for path in [root, root / "bin", root / "bin" / "run"]:
        info = path.stat()
        assert (info.st_uid, info.st_gid) == (0, 0)
        assert not info.st_mode & 0o6022
    # Worker umask may be 0077: root ownership must not make the app unreadable.
    assert stat.S_IMODE((root / "bin" / "run").stat().st_mode) == 0o755
    assert paths.current.resolve() == journal.prior_target


def test_freeze_private_worker_modes_become_service_readable(tree):
    root = tree / "candidate"
    root.mkdir(mode=0o700)
    (root / "data").write_bytes(b"public release code")
    (root / "data").chmod(0o600)
    secure_fs.freeze_tree(root, 0)
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "data").stat().st_mode) == 0o644


@pytest.mark.parametrize("ignored", ["fchown", "fchmod"])
def test_freeze_refuses_filesystem_ignoring_metadata_changes(tree, monkeypatch, ignored):
    root = tree / "candidate"
    root.mkdir(mode=0o700)
    os.chown(root, 0, 12345)
    monkeypatch.setattr(os, ignored, lambda *args: None)
    with pytest.raises((ValueError, OSError)):
        secure_fs.freeze_tree(root, 0)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "owner", "setid", "writable"])
def test_freeze_rejects_unsafe_complete_tree_before_ownership_change(tree, kind):
    _, journal = candidate(tree)
    root = journal.candidate
    bad = root / "bad"
    if kind == "symlink":
        bad.symlink_to(tree / "unrelated")
    elif kind == "hardlink":
        os.link(tree / "unrelated", bad)
    elif kind == "fifo":
        os.mkfifo(bad)
    else:
        bad.write_bytes(b"bad")
        if kind == "owner":
            os.chown(bad, 12345, 12345)
        elif kind == "setid":
            bad.chmod(0o2644)
        else:
            bad.chmod(0o666)
    with pytest.raises((ValueError, OSError)):
        secure_fs.freeze_tree(root, 0)
    assert root.stat().st_uid == 0


def test_remove_only_recorded_unpublished_candidate(tree):
    paths, journal = candidate(tree)
    secure_fs.remove_candidate(paths, journal)
    assert not journal.candidate.exists()
    assert journal.prior_target.is_dir()
    assert paths.current.resolve() == journal.prior_target


@pytest.mark.parametrize("reason", ["unrecorded", "published", "prior", "current", "identity"])
def test_remove_refuses_ambiguous_or_published_candidate(tree, reason):
    paths, journal = candidate(tree)
    if reason == "unrecorded":
        journal = replace(journal, candidate_created=False)
    elif reason == "published":
        journal = replace(journal, candidate_published=True)
    elif reason == "prior":
        journal = replace(journal, prior_target=journal.candidate)
    elif reason == "current":
        paths.current.unlink()
        paths.current.symlink_to(journal.candidate)
    else:
        journal = replace(journal, candidate_identity=(0, 0))
    with pytest.raises((ValueError, OSError)):
        secure_fs.remove_candidate(paths, journal)
    assert (journal.candidate / "bin" / "run").read_bytes() == b"executable"


def test_remove_refuses_symlinks_instead_of_following_them(tree):
    paths, journal = candidate(tree)
    (journal.candidate / "escape").symlink_to(tree)
    with pytest.raises((ValueError, OSError)):
        secure_fs.remove_candidate(paths, journal)
    assert (journal.candidate / "bin" / "run").exists()


def test_remove_refuses_current_disagreeing_with_prior_journal(tree):
    paths, journal = candidate(tree)
    other = paths.releases / "0.9.0"
    other.mkdir()
    paths.current.unlink()
    paths.current.symlink_to(other)
    with pytest.raises(ValueError):
        secure_fs.remove_candidate(paths, journal)
    assert (journal.candidate / "bin" / "run").exists()


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_remove_refuses_missing_or_unsafe_prior_target(tree, kind):
    paths, journal = candidate(tree)
    journal.prior_target.rmdir()
    if kind == "symlink":
        journal.prior_target.symlink_to(tree, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        secure_fs.remove_candidate(paths, journal)
    assert (journal.candidate / "bin" / "run").exists()


@pytest.mark.parametrize("change", [{"candidate_created": "false"}, {"candidate_published": ""}])
def test_remove_requires_explicit_boolean_journal_provenance(tree, change):
    paths, journal = candidate(tree)
    with pytest.raises(ValueError):
        secure_fs.remove_candidate(paths, replace(journal, **change))
    assert (journal.candidate / "bin" / "run").exists()


@pytest.mark.parametrize("operation", ["freeze", "remove"])
def test_moved_descendant_directory_not_mutated_via_held_fd(tree, monkeypatch, operation):
    paths, journal = candidate(tree)
    root = journal.candidate
    file = root / "bin" / "run"
    if operation == "freeze":
        for path in [file, root / "bin", root]:
            os.chown(path, 12345, 12345)
    # Trigger immediately before the first per-entry mutation check, after validation.
    fstat = os.fstat
    raced = False
    checks = 0
    inode = file.stat().st_ino

    def move_parent(fd):
        nonlocal raced, checks
        info = fstat(fd)
        if info.st_ino == inode:
            checks += 1
            if checks == 4 and not raced:
                raced = True
                (root / "bin").rename(tree / "escaped")
                (root / "bin").mkdir()
        return info

    monkeypatch.setattr(os, "fstat", move_parent)
    with pytest.raises((ValueError, OSError)):
        if operation == "freeze":
            secure_fs.freeze_tree(root, 12345)
        else:
            secure_fs.remove_candidate(paths, journal)
    assert raced
    assert (tree / "escaped" / "run").read_bytes() == b"executable"
    if operation == "freeze":
        assert (tree / "escaped" / "run").stat().st_uid == 12345


def test_freeze_invalid_late_entry_does_not_partially_chown(tree):
    _, journal = candidate(tree)
    root = journal.candidate
    for path in [root / "bin" / "run", root / "bin", root]:
        os.chown(path, 12345, 12345)
    (root / "zzz").symlink_to(tree / "unrelated")
    with pytest.raises((ValueError, OSError)):
        secure_fs.freeze_tree(root, 12345)
    for path in [root / "bin" / "run", root / "bin", root]:
        assert path.stat().st_uid == 12345


@pytest.mark.parametrize("operation", ["read", "write", "freeze", "remove"])
def test_cross_device_entry_rejected(tree, monkeypatch, operation):
    paths, journal = candidate(tree)
    target = journal.candidate / "bin" / "run"
    fstat = os.fstat
    inode = target.stat().st_ino

    def different_device(fd):
        info = fstat(fd)
        if info.st_ino == inode:
            values = list(info)
            values[2] += 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", different_device)
    with pytest.raises((ValueError, OSError)):
        if operation == "read":
            secure_fs.read_regular(target, 20)
        elif operation == "write":
            secure_fs.atomic_write(target, b"new", 0, 0, 0o600)
        elif operation == "freeze":
            secure_fs.freeze_tree(journal.candidate, 0)
        else:
            secure_fs.remove_candidate(paths, journal)
    assert target.read_bytes() == b"executable"


@pytest.mark.parametrize("operation", ["read", "write", "freeze", "remove"])
def test_same_device_mount_boundary_rejected(tree, monkeypatch, operation):
    paths, journal = candidate(tree)
    target = journal.candidate / "bin" / "run"
    inode = target.stat().st_ino
    # Bind mounts have the same st_dev. Inject only the kernel mount-ID boundary,
    # retaining real open/stat/write behavior and checking no content was changed.
    mount_id = getattr(secure_fs, "_mount_id", lambda fd: 1)

    def mounted(fd):
        if os.fstat(fd).st_ino == inode:
            return -1
        return mount_id(fd)

    monkeypatch.setattr(secure_fs, "_mount_id", mounted, raising=False)
    with pytest.raises((ValueError, OSError)):
        if operation == "read":
            secure_fs.read_regular(target, 20)
        elif operation == "write":
            secure_fs.atomic_write(target, b"new", 0, 0, 0o600)
        elif operation == "freeze":
            secure_fs.freeze_tree(journal.candidate, 0)
        else:
            secure_fs.remove_candidate(paths, journal)
    assert target.read_bytes() == b"executable"
