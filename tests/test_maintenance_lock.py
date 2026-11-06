"""Behavioral tests for setup's shared/exclusive maintenance lock."""

import grp
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK_HELPER = ROOT / "installer" / "maintenance_lock.sh"


def run_lock_script(lock_file, body):
    environment = os.environ.copy()
    environment["KNXOH_MAINTENANCE_LOCK_FILE"] = str(lock_file)
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; ' + body, "lock-test", str(LOCK_HELPER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_ensure_lock_creates_secure_regular_file_without_truncating_existing_inode(tmp_path):
    lock_file = tmp_path / "private lock dir" / "maintenance.lock"
    lock_file.parent.mkdir()
    lock_file.write_text("existing inode data", encoding="utf-8")
    original_inode = lock_file.stat().st_ino
    group_name = grp.getgrgid(os.getgid()).gr_name

    result = run_lock_script(
        lock_file,
        'ensure_maintenance_lock "$(id -gn)"',
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert lock_file.stat().st_ino == original_inode
    assert lock_file.read_text(encoding="utf-8") == "existing inode data"
    assert lock_file.stat().st_uid == 0
    assert lock_file.stat().st_mode & 0o777 == 0o660
    assert grp.getgrgid(lock_file.stat().st_gid).gr_name == group_name
    assert lock_file.parent.stat().st_uid == 0
    assert lock_file.parent.stat().st_mode & 0o777 == 0o750


def test_shared_and_exclusive_locks_are_mutually_exclusive_and_releaseable(tmp_path):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    result = run_lock_script(
        lock_file,
        "acquire_maintenance_exclusive_lock || exit 10; "
        'if flock --nonblock --shared "$KNXOH_MAINTENANCE_LOCK_FILE" -c true; then exit 11; '
        "else status=$?; fi; "
        '[[ "$status" == 1 ]] || exit 12; '
        "release_maintenance_lock || exit 13; "
        "acquire_maintenance_shared_lock || exit 14; "
        'if flock --nonblock --exclusive "$KNXOH_MAINTENANCE_LOCK_FILE" -c true; then exit 15; '
        "else status=$?; fi; "
        '[[ "$status" == 1 ]] || exit 16; '
        "release_maintenance_lock",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_lock_descriptor_remains_held_across_exec(tmp_path):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    result = run_lock_script(
        lock_file,
        "acquire_maintenance_shared_lock || exit 10; "
        'exec flock --nonblock --exclusive "$KNXOH_MAINTENANCE_LOCK_FILE" -c true',
    )

    assert result.returncode == 1
