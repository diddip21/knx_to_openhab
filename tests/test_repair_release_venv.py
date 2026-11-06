"""Integration tests for active transactional-release environment recovery."""

import fcntl
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPAIR_SCRIPT = ROOT / "installer" / "repair_release_venv.sh"


def create_install(tmp_path):
    install = tmp_path / "install with spaces"
    release = install / "releases" / "active release"
    data = tmp_path / "runtime data"
    config = tmp_path / "configuration"
    backups = tmp_path / "backups"
    for directory in (release / "installer", data, config, backups):
        directory.mkdir(parents=True, exist_ok=True)
    (install / "current").symlink_to("releases/active release")
    (release / "requirements.txt").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "knxoh_paths.py", release / "knxoh_paths.py")
    (release / "web_ui" / "backend").mkdir(parents=True)
    (release / "web_ui" / "__init__.py").write_text("", encoding="utf-8")
    (release / "web_ui" / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (release / "web_ui" / "backend" / "auth.py").write_text(
        "def is_password_hash(value):\n    return bool(value)\n", encoding="utf-8"
    )

    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        "\n".join(
            (
                f"KNXOH_INSTALL_DIR={shlex.quote(str(install))}",
                f"KNXOH_CONFIG_DIR={shlex.quote(str(config))}",
                f"KNXOH_DATA_DIR={shlex.quote(str(data))}",
                f"KNXOH_BACKUP_DIR={shlex.quote(str(backups))}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    helper = release / "installer" / REPAIR_SCRIPT.name
    assert REPAIR_SCRIPT.is_file(), "active-release virtualenv repair helper is not implemented"
    shutil.copy2(REPAIR_SCRIPT, helper)
    helper.chmod(0o755)
    return {
        "install": install,
        "release": release,
        "data": data,
        "paths_file": paths_file,
        "helper": helper,
    }


def helper_environment(installation, extra=None):
    environment = os.environ.copy()
    for name in (
        "KNXOH_INSTALL_DIR",
        "KNXOH_CONFIG_DIR",
        "KNXOH_DATA_DIR",
        "KNXOH_BACKUP_DIR",
    ):
        environment.pop(name, None)
    environment["KNXOH_PATHS_FILE"] = str(installation["paths_file"])
    if extra:
        environment.update(extra)
    return environment


def run_helper(installation, environment=None):
    return subprocess.run(
        ["bash", str(installation["helper"])],
        cwd=installation["release"],
        env=environment or helper_environment(installation),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def create_fake_python3(fake_bin, *, stub_python=False):
    fake_bin.mkdir(parents=True, exist_ok=True)
    wrapper = fake_bin / "python3"
    wrapper.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then\n'
        '  "$REPAIR_TEST_REAL_PYTHON" "$@" || exit $?\n'
        '  target="$3"\n'
        "  cat > \"$target/bin/pip\" <<'PIP'\n"
        "#!/bin/bash\n"
        'if [[ "${REPAIR_TEST_PIP_FAIL:-0}" == "1" && "${1:-}" == "install" ]]; then\n'
        "  exit 17\n"
        "fi\n"
        'script_dir="$(cd "$(dirname "$0")" && pwd)"\n'
        'exec "$script_dir/python" -m pip "$@"\n'
        "PIP\n"
        '  chmod 755 "$target/bin/pip"\n'
        + (
            '  rm -f "$target/bin/python"\n'
            "  cat > \"$target/bin/python\" <<'PYTHON'\n"
            "#!/bin/bash\n"
            "exit 0\n"
            "PYTHON\n"
            '  chmod 755 "$target/bin/python"\n'
            if stub_python
            else ""
        )
        + "  exit 0\n"
        "fi\n"
        'exec "$REPAIR_TEST_REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def test_repair_release_venv_creates_environment_at_active_final_path(tmp_path):
    installation = create_install(tmp_path)

    result = run_helper(installation)

    assert result.returncode == 0, result.stdout + result.stderr
    python = installation["release"] / "venv" / "bin" / "python"
    assert python.is_file()
    assert os.access(python, os.X_OK)
    identity = subprocess.run(
        [str(python), "-c", "import sys; print(sys.prefix)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert identity.stdout.strip() == str(installation["release"] / "venv")


@pytest.mark.parametrize("target_kind", ["stale-release", "outside-releases"])
def test_repair_release_venv_rejects_stale_or_unsafe_release(tmp_path, target_kind):
    installation = create_install(tmp_path)
    current = installation["install"] / "current"
    current.unlink()
    if target_kind == "stale-release":
        target = installation["install"] / "releases" / "other release"
        target.mkdir()
    else:
        target = tmp_path / "outside release"
        target.mkdir()
    current.symlink_to(target)

    result = run_helper(installation)

    assert result.returncode != 0
    assert not (installation["release"] / "venv").exists()
    assert current.resolve() == target.resolve()


def test_repair_release_venv_refuses_busy_updater_lock(tmp_path):
    installation = create_install(tmp_path)
    lock_path = installation["data"] / "updater.lock"
    lock_path.touch()

    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_helper(installation)

    assert result.returncode != 0
    assert "updater" in (result.stdout + result.stderr).lower()
    assert not (installation["release"] / "venv").exists()
    assert (installation["install"] / "current").resolve() == installation["release"]


def test_repair_release_venv_restores_previous_venv_after_failure(tmp_path):
    installation = create_install(tmp_path)
    previous_venv = installation["release"] / "venv"
    previous_venv.mkdir()
    marker = previous_venv / "partial-install-marker"
    marker.write_text("preserve on failure", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    create_fake_python3(fake_bin)
    environment = helper_environment(
        installation,
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REPAIR_TEST_REAL_PYTHON": sys.executable,
            "REPAIR_TEST_PIP_FAIL": "1",
        },
    )

    result = run_helper(installation, environment)

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "preserve on failure"
    assert list(installation["release"].glob(".venv-repair-backup-*")) == []
    assert (installation["install"] / "current").resolve() == installation["release"]


def test_repair_release_venv_is_idempotent(tmp_path):
    installation = create_install(tmp_path)
    first_result = run_helper(installation)
    assert first_result.returncode == 0, first_result.stdout + first_result.stderr
    marker = installation["release"] / "venv" / "keep-on-repeat"
    marker.write_text("already repaired", encoding="utf-8")

    second_result = run_helper(installation)

    assert second_result.returncode == 0, second_result.stdout + second_result.stderr
    assert marker.read_text(encoding="utf-8") == "already repaired"


def test_recovery_command_repairs_active_venv_and_retry_passes_preflight(tmp_path):
    installation = create_install(tmp_path)
    release = installation["release"]
    (release / "version.json").write_text(
        '{"release_tag":"v1.2.3","commit_hash":"' + "a" * 40 + '"}\n',
        encoding="utf-8",
    )
    active_update = release / "update.sh"
    shutil.copy2(ROOT / "update.sh", active_update)
    fake_bin = tmp_path / "bin"
    create_fake_python3(fake_bin, stub_python=True)
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-n" && "${2:-}" == "-l" ]]; then\n'
        '  echo "NOPASSWD: limited service commands"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-u" && "${2:-}" == "knxohui" ]]; then\n'
        "  shift 2\n"
        '  exec "$@"\n'
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    environment = helper_environment(
        installation,
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "INSTALL_DIR": str(installation["install"]),
            "KNXOH_INSTALL_DIR": str(installation["install"]),
            "KNXOH_DATA_DIR": str(installation["data"]),
            "KNXOH_CONFIG_DIR": str(tmp_path / "configuration"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "backups"),
            "LOG_FILE": str(tmp_path / "update.log"),
            "RELEASE_TAG": "v1.2.3",
            "RELEASE_COMMIT_HASH": "a" * 40,
            "REPAIR_TEST_REAL_PYTHON": sys.executable,
        },
    )

    first_update = subprocess.run(
        ["bash", str(active_update)],
        cwd=installation["install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert first_update.returncode == 1, first_update.stdout + first_update.stderr
    recovery_line = next(
        (line for line in first_update.stdout.splitlines() if "Recovery: run " in line), ""
    )
    assert recovery_line, first_update.stdout + first_update.stderr
    command = recovery_line.split("Recovery: run ", 1)[1].split(" from ", 1)[0].strip(" '\"")
    command_args = shlex.split(command)
    assert command_args == [
        "sudo",
        "-u",
        "knxohui",
        "bash",
        str(installation["helper"]),
    ]

    repair_result = subprocess.run(
        command_args,
        cwd=installation["install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert repair_result.returncode == 0, repair_result.stdout + repair_result.stderr
    assert os.access(installation["release"] / "venv" / "bin" / "python", os.X_OK)
    assert (installation["install"] / "current").resolve() == release

    retry = subprocess.run(
        ["bash", str(active_update)],
        cwd=installation["install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert "External Web UI and generator configuration are ready." in retry.stdout
    assert "Already running selected release v1.2.3." in retry.stdout
    assert "active release is incomplete" not in retry.stdout
