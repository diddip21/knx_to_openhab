"""Tests for recovery of interrupted releases before the Web UI starts."""

import fcntl
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "installer" / "launch_web.sh"


def _make_app(app_dir: Path) -> Path:
    gunicorn = app_dir / "venv" / "bin" / "gunicorn"
    gunicorn.parent.mkdir(parents=True)
    gunicorn.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' {shlex.quote(app_dir.name)}\n", encoding="utf-8"
    )
    gunicorn.chmod(0o755)
    return gunicorn


def _launch(install_dir: Path, data_dir: Path) -> subprocess.CompletedProcess[str]:
    paths_file = data_dir / "paths.env"
    lock_file = data_dir / "maintenance.lock"
    paths_file.write_text(
        f"KNXOH_MAINTENANCE_LOCK_FILE={shlex.quote(str(lock_file))}\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "KNXOH_MAINTENANCE_LOCK_FILE": str(lock_file),
        }
    )
    lock_file.touch()
    test_launcher_dir = install_dir / ".test-lock-aware-launcher"
    test_launcher_dir.mkdir(exist_ok=True)
    test_launcher = test_launcher_dir / "launch_web.sh"
    shutil.copy2(LAUNCHER, test_launcher)
    test_lock_helper = test_launcher_dir / "maintenance_lock.sh"
    test_lock_helper.write_text(
        (ROOT / "installer" / "maintenance_lock.sh").read_text(encoding="utf-8")
        + "\n_validate_maintenance_lock_ancestors() { return 0; }\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(test_launcher)],
        cwd=install_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _make_transactional_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    install_dir = tmp_path / "install"
    releases = install_dir / "releases"
    data_dir = tmp_path / "data"
    releases.mkdir(parents=True)
    data_dir.mkdir()
    previous_release = releases / "previous"
    candidate_release = releases / "candidate"
    _make_app(previous_release)
    _make_app(candidate_release)
    (install_dir / "current").symlink_to("releases/candidate")
    return install_dir, data_dir, previous_release


def test_launcher_does_not_change_current_without_marker(tmp_path):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)

    result = _launch(install_dir, data_dir)

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve().name == "candidate"
    assert result.stdout.strip() == "candidate"


def test_launcher_restores_previous_release_with_stale_marker(tmp_path):
    install_dir, data_dir, previous_release = _make_transactional_install(tmp_path)
    candidate_release = install_dir / "releases/candidate"
    (candidate_release / ".update-in-progress").write_text("releases/previous\n", encoding="utf-8")

    result = _launch(install_dir, data_dir)

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == previous_release
    assert result.stdout.strip() == "previous"
    assert (candidate_release / ".update-in-progress").is_file()


def test_launcher_restores_legacy_install_with_stale_marker(tmp_path):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)
    _make_app(install_dir)
    candidate_release = install_dir / "releases/candidate"
    (candidate_release / ".update-in-progress").write_text("legacy\n", encoding="utf-8")

    result = _launch(install_dir, data_dir)

    assert result.returncode == 0, result.stderr
    assert not (install_dir / "current").is_symlink()
    assert result.stdout.strip() == "install"


def test_launcher_does_not_rollback_while_update_lock_is_held(tmp_path):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)
    candidate_release = install_dir / "releases/candidate"
    (candidate_release / ".update-in-progress").write_text("releases/previous\n", encoding="utf-8")
    lock_path = data_dir / "updater.lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = _launch(install_dir, data_dir)

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == candidate_release
    assert result.stdout.strip() == "candidate"


@pytest.mark.parametrize(
    "marker", ["", "../../outside", "releases/missing", "releases/previous\n\n"]
)
def test_launcher_rejects_unsafe_rollback_target(tmp_path, marker):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)
    candidate_release = install_dir / "releases/candidate"
    (candidate_release / ".update-in-progress").write_text(marker, encoding="utf-8")

    result = _launch(install_dir, data_dir)

    assert result.returncode != 0
    assert (install_dir / "current").resolve() == candidate_release
    assert (candidate_release / ".update-in-progress").is_file()
    assert result.stdout == ""


def test_launcher_fails_closed_when_update_lock_is_a_symlink(tmp_path):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)
    external_lock = tmp_path / "external.lock"
    external_lock.touch()
    (data_dir / "updater.lock").symlink_to(external_lock)

    result = _launch(install_dir, data_dir)

    assert result.returncode != 0
    assert (install_dir / "current").resolve().name == "candidate"
    assert result.stdout == ""


def test_launcher_rejects_nul_byte_in_recovery_marker(tmp_path):
    install_dir, data_dir, _ = _make_transactional_install(tmp_path)
    candidate_release = install_dir / "releases/candidate"
    marker = candidate_release / ".update-in-progress"
    marker.write_bytes(b"releases/previous\x00ignored\n")

    result = _launch(install_dir, data_dir)

    assert result.returncode != 0
    assert (install_dir / "current").resolve() == candidate_release
    assert marker.is_file()
    assert result.stdout == ""
