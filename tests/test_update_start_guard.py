"""Startup checks must work without the private journal or lifecycle lock."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from installer.update_core import state
from installer.update_start_guard import check_start_allowed
from tests.test_update_state import paths  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX protected filesystem")


def permit(paths):
    config = paths.config_dir / "config.json"
    config.write_bytes(b"coherent")
    digest = hashlib.sha256(b"coherent").hexdigest()
    state.write_gate(paths, "permit", paths.releases / "1.0.0", digest)


def test_absent_deny_permit_clear_and_no_lock(paths):
    # Holding the real lifecycle lock cannot impede any guard check.
    with state.LifecycleLock(paths.config_dir / "lock").acquire():
        assert check_start_allowed(paths, "ui")
        assert check_start_allowed(paths, "cleanup")
        assert not check_start_allowed(paths, "unknown")
        state.write_gate(paths, "deny", None, None)
        assert not check_start_allowed(paths, "ui")
        assert not check_start_allowed(paths, "cleanup")
        permit(paths)
        assert check_start_allowed(paths, "ui")
        assert not check_start_allowed(paths, "cleanup")
        state.write_gate(paths, "clear", None, None)
        assert check_start_allowed(paths, "cleanup")


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "current",
        "malformed",
        "future",
        "symlink",
        "owner",
        "writable",
        "unreadable",
        "parent",
        "missing-current",
        "candidate-writable",
        "gate-hardlink",
    ],
)
def test_mismatched_or_unsafe_pair_blocks_both_roles(paths, change):
    permit(paths)
    gate = paths.config_dir / ".updater-startup-gate.json"
    if change == "digest":
        (paths.config_dir / "config.json").write_bytes(b"changed")
    elif change == "current":
        paths.current.unlink()
        paths.current.symlink_to(paths.releases / "2.0.0")
    elif change == "missing-current":
        paths.current.unlink()
    elif change == "candidate-writable":
        (paths.releases / "1.0.0").chmod(0o777)
    elif change == "malformed":
        gate.write_bytes(b"not-json")
    elif change == "future":
        gate.write_bytes(b'{"format_version":2,"mode":"deny"}')
    elif change == "symlink":
        gate.unlink()
        gate.symlink_to(paths.config_dir / "missing")
    elif change == "owner":
        os.chown(gate, 12345, 12345)
    elif change == "writable":
        gate.chmod(0o666)
    elif change == "unreadable":
        gate.chmod(0)
    elif change == "parent":
        paths.config_dir.chmod(0o777)
    else:
        os.link(gate, paths.config_dir / "second")
    assert not check_start_allowed(paths, "ui")
    assert not check_start_allowed(paths, "cleanup")


def test_absent_gate_does_not_bypass_unsafe_paths(paths):
    paths.config_dir.chmod(0o777)
    assert not check_start_allowed(paths, "ui")


def test_standalone_isolated_cli_validates_bundle_and_ignores_candidate_code(paths):
    bundle = paths.config_dir.parent / "libexec"
    bundle.mkdir()
    installer = Path(__file__).resolve().parents[1] / "installer"
    shutil.copyfile(installer / "update_start_guard.py", bundle / "update_start_guard.py")
    shutil.copytree(
        installer / "update_core",
        bundle / "update_core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # Model administrator installation, not DrvFS's source checkout modes (0777).
    for path in bundle.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    marker = paths.config_dir / "candidate-executed"
    (paths.releases / "1.0.0/sitecustomize.py").write_text(
        f"open({str(marker)!r}, 'w').write('bad')"
    )
    command = [
        "/usr/bin/python3",
        "-I",
        str(bundle / "update_start_guard.py"),
        "--releases",
        str(paths.releases),
        "--current",
        str(paths.current),
        "--config-dir",
        str(paths.config_dir),
        "--role",
        "ui",
    ]
    result = subprocess.run(command, cwd=paths.releases / "1.0.0", capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert subprocess.run([command[0], *command[2:]], capture_output=True).returncode != 0
    # An administrator may replace the installed bundle while this lock-free
    # reader runs. Execute the bytes held/validated through the no-follow FD,
    # never a second path-based read of different source after validation.
    replaced = paths.config_dir / "unvalidated-source-executed"
    harness = f"""
import importlib.util, os, pathlib
spec = importlib.util.spec_from_file_location('guard', {str(bundle / 'update_start_guard.py')!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
close = os.close
changed = False
def swap_after_validation(fd):
    global changed
    target = os.readlink('/proc/self/fd/' + str(fd))
    close(fd)
    if target == {str(bundle / 'update_core/state.py')!r} and not changed:
        changed = True
        pathlib.Path(target).write_text({f'open({str(replaced)!r}, "w").write("bad")'!r})
os.close = swap_after_validation
paths_type, check = guard._trusted_core()
assert check(paths_type(pathlib.Path({str(paths.releases)!r}),
                       pathlib.Path({str(paths.current)!r}),
                       pathlib.Path({str(paths.config_dir)!r})), 'ui')
"""
    assert (
        subprocess.run(["/usr/bin/python3", "-I", "-c", harness], capture_output=True).returncode
        == 0
    )
    assert not replaced.exists()
    (bundle / "update_core/state.py").chmod(0o666)
    assert subprocess.run(command, capture_output=True).returncode != 0


def test_real_unprivileged_guard_cannot_read_journal_and_needs_no_lock(paths):
    from installer.update_core.protocol import Paths

    # /root is deliberately not service-traversable. This isolated test fixture
    # has a readable parent; ONLY its recovery directory is private. No host
    # service, identity, policy, or ancestor permissions are changed.
    with tempfile.TemporaryDirectory(prefix="knxoh-guard-", dir="/var/lib") as directory:
        root = Path(directory)
        root.chmod(0o755)
        for name in ("config", "releases", "libexec"):
            (root / name).mkdir()
        (root / "releases/1.0.0").mkdir()
        (root / "current").symlink_to(root / "releases/1.0.0")
        guarded = Paths(root / "releases", root / "current", root / "config")
        store = state.StateStore(guarded)
        store.journal_path.write_bytes(b"private invalid journal must not be consulted")
        source = Path(__file__).resolve().parents[1] / "installer"
        shutil.copyfile(source / "update_start_guard.py", root / "libexec/update_start_guard.py")
        shutil.copytree(
            source / "update_core",
            root / "libexec/update_core",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for path in (root / "libexec").rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        command = [
            "/usr/bin/python3",
            "-I",
            str(root / "libexec/update_start_guard.py"),
            "--releases",
            str(guarded.releases),
            "--current",
            str(guarded.current),
            "--config-dir",
            str(guarded.config_dir),
            "--role",
        ]

        def run(role):
            return subprocess.run(
                command + [role],
                user=65534,
                group=65534,
                extra_groups=[],
                cwd="/",
                capture_output=True,
                timeout=10,
            ).returncode

        with state.LifecycleLock(root / "lock").acquire():
            assert run("ui") == 0
            permit(guarded)
            assert run("ui") == 0
            assert run("cleanup") == 1
            (guarded.config_dir / ".updater-startup-gate.json").chmod(0o600)
            assert run("ui") == 1
