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
MAINTENANCE_LOCK_HELPER = ROOT / "installer" / "maintenance_lock.sh"


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
    shutil.copy2(ROOT / "knxoh_paths.py", install / "knxoh_paths.py")

    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        "\n".join(
            (
                f"KNXOH_INSTALL_DIR={shlex.quote(str(install))}",
                f"KNXOH_CONFIG_DIR={shlex.quote(str(config))}",
                f"KNXOH_DATA_DIR={shlex.quote(str(data))}",
                f"KNXOH_BACKUP_DIR={shlex.quote(str(backups))}",
                f"KNXOH_MAINTENANCE_LOCK_FILE={shlex.quote(str(data / 'maintenance.lock'))}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    helper = release / "installer" / REPAIR_SCRIPT.name
    assert REPAIR_SCRIPT.is_file(), "active-release virtualenv repair helper is not implemented"
    shutil.copy2(REPAIR_SCRIPT, helper)
    helper.chmod(0o755)
    _copy_test_maintenance_lock_helper(release / "installer" / MAINTENANCE_LOCK_HELPER.name)
    (data / "maintenance.lock").touch()
    fake_bin = tmp_path / "helper-fake-bin"
    create_fake_python3(fake_bin)
    return {
        "install": install,
        "release": release,
        "data": data,
        "paths_file": paths_file,
        "helper": helper,
        "fake_bin": fake_bin,
    }


def install_stable_helper(installation, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPAIR_SCRIPT, destination)
    destination.chmod(0o755)
    _copy_test_maintenance_lock_helper(destination.parent / MAINTENANCE_LOCK_HELPER.name)
    shutil.copy2(ROOT / "knxoh_paths.py", installation["install"] / "knxoh_paths.py")
    return destination


def _copy_test_maintenance_lock_helper(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        MAINTENANCE_LOCK_HELPER.read_text(encoding="utf-8")
        + "\n_validate_maintenance_lock_ancestors() { return 0; }\n",
        encoding="utf-8",
    )
    destination.chmod(0o755)


def helper_environment(installation, extra=None):
    environment = os.environ.copy()
    for name in (
        "KNXOH_INSTALL_DIR",
        "KNXOH_CONFIG_DIR",
        "KNXOH_DATA_DIR",
        "KNXOH_BACKUP_DIR",
    ):
        environment.pop(name, None)
    environment["KNXOH_INSTALL_DIR"] = str(installation["install"])
    environment["KNXOH_DATA_DIR"] = str(installation["data"])
    environment["KNXOH_EXPECTED_RELEASE"] = str(installation["release"])
    environment["KNXOH_PATHS_FILE"] = str(installation["paths_file"])
    environment["KNXOH_MAINTENANCE_LOCK_FILE"] = str(installation["data"] / "maintenance.lock")
    environment["PATH"] = f"{installation['fake_bin']}{os.pathsep}{os.environ['PATH']}"
    environment["REPAIR_TEST_REAL_PYTHON"] = sys.executable
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
        '  target_site="$("$target/bin/python" -c "import sysconfig; print(sysconfig.get_paths()[\'purelib\'])")"\n'
        "  for module in flask gunicorn requests xknxproject yaml; do\n"
        '    printf "# test dependency\\n" > "$target_site/$module.py"\n'
        "  done\n"
        '  mkdir -p "$target_site/argon2"\n'
        '  printf "# test dependency\\n" > "$target_site/argon2/__init__.py"\n'
        "  cat > \"$target/bin/gunicorn\" <<'GUNICORN'\n"
        "#!/bin/sh\n"
        "exit 0\n"
        "GUNICORN\n"
        '  chmod 755 "$target/bin/gunicorn"\n'
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


def create_existing_venv(installation):
    venv = installation["release"] / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=60)
    return venv


def test_repair_rebuilds_venv_when_runtime_dependency_is_missing(tmp_path):
    installation = create_install(tmp_path)
    venv = create_existing_venv(installation)
    marker = venv / "preexisting-venv-marker"
    marker.write_text("preserve if rebuild fails", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    create_fake_python3(fake_bin)
    environment = helper_environment(
        installation,
        {
            "PATH": (
                f"{fake_bin}{os.pathsep}{installation['fake_bin']}"
                f"{os.pathsep}{os.environ['PATH']}"
            ),
            "REPAIR_TEST_REAL_PYTHON": sys.executable,
            "REPAIR_TEST_PIP_FAIL": "1",
        },
    )

    result = run_helper(installation, environment)

    assert result.returncode != 0
    assert "could not install" in (result.stdout + result.stderr).lower()
    assert marker.read_text(encoding="utf-8") == "preserve if rebuild fails"


def test_repair_does_not_accept_venv_without_gunicorn_entrypoint(tmp_path):
    installation = create_install(tmp_path)
    venv = installation["release"] / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    marker = venv / "preexisting-venv-marker"
    marker.write_text("preserve if rebuild fails", encoding="utf-8")
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
    assert "could not install" in (result.stdout + result.stderr).lower()
    assert marker.read_text(encoding="utf-8") == "preserve if rebuild fails"
    assert not (venv / "bin" / "gunicorn").exists()


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


def test_repair_rejects_environment_overrides_that_conflict_with_saved_paths(tmp_path):
    configured = create_install(tmp_path / "configured")
    overridden = create_install(tmp_path / "overridden")
    environment = helper_environment(
        configured,
        {
            "KNXOH_INSTALL_DIR": str(overridden["install"]),
            "KNXOH_DATA_DIR": str(overridden["data"]),
            "KNXOH_EXPECTED_RELEASE": str(overridden["release"]),
        },
    )

    result = run_helper(configured, environment)

    assert result.returncode != 0
    assert "do not match the configured paths file" in (result.stdout + result.stderr)
    assert not (overridden["release"] / "venv").exists()
    assert (configured["install"] / "current").resolve() == configured["release"]


def test_repair_release_venv_refuses_busy_updater_lock(tmp_path):
    installation = create_install(tmp_path)
    lock_path = installation["data"] / "updater.lock"
    lock_path.touch()

    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_helper(
            installation,
            helper_environment(installation, {"KNXOH_SETUP_LOCK_HELD": "1"}),
        )

    assert result.returncode != 0
    assert "updater" in (result.stdout + result.stderr).lower()
    assert not (installation["release"] / "venv").exists()
    assert (installation["install"] / "current").resolve() == installation["release"]


def test_repair_uses_saved_custom_lock_path_when_environment_is_unset(tmp_path):
    installation = create_install(tmp_path)
    saved_lock = installation["data"] / "maintenance locks" / "maintenance.lock"
    saved_lock.parent.mkdir()
    saved_lock.touch()
    paths_file = installation["paths_file"]
    contents = paths_file.read_text(encoding="utf-8")
    default_line = (
        f"KNXOH_MAINTENANCE_LOCK_FILE={shlex.quote(str(installation['data'] / 'maintenance.lock'))}"
    )
    paths_file.write_text(
        contents.replace(
            default_line, f"KNXOH_MAINTENANCE_LOCK_FILE={shlex.quote(str(saved_lock))}"
        ),
        encoding="utf-8",
    )
    environment = helper_environment(installation)
    environment.pop("KNXOH_MAINTENANCE_LOCK_FILE")

    with saved_lock.open("r+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_helper(installation, environment)

    assert result.returncode != 0
    output = (result.stdout + result.stderr).lower()
    assert "setup or uninstall is in progress" in output
    assert "maintenance lock file is missing or unsafe" not in output
    assert not (installation["release"] / "venv").exists()


def test_repair_rejects_conflicting_maintenance_lock_override(tmp_path):
    installation = create_install(tmp_path)
    environment = helper_environment(
        installation,
        {"KNXOH_MAINTENANCE_LOCK_FILE": str(installation["data"] / "other.lock")},
    )

    result = run_helper(installation, environment)

    assert result.returncode != 0
    assert "conflicts with the persisted" in (result.stdout + result.stderr)
    assert not (installation["release"] / "venv").exists()


def test_repair_release_venv_accepts_setup_inherited_updater_lock(tmp_path):
    installation = create_install(tmp_path)
    lock_path = installation["data"] / "updater.lock"
    lock_path.touch()

    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_helper(
            installation,
            helper_environment(
                installation,
                {
                    "KNXOH_SETUP_LOCK_HELD": "1",
                    "KNXOH_SETUP_UPDATER_LOCK_HELD": "1",
                },
            ),
        )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (installation["release"] / "venv/bin/gunicorn").is_file()
    assert (installation["install"] / "current").resolve() == installation["release"]


def test_repair_release_venv_refuses_to_run_during_setup_maintenance_lock(tmp_path):
    installation = create_install(tmp_path)
    lock_path = installation["data"] / "maintenance.lock"

    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_helper(installation)

    assert result.returncode != 0
    assert "setup or uninstall is in progress" in (result.stdout + result.stderr).lower()
    assert not (installation["release"] / "venv").exists()


def test_stable_repair_helper_recovers_release_without_local_helper(tmp_path):
    installation = create_install(tmp_path)
    installation["helper"].unlink()
    stable_helper = install_stable_helper(
        installation,
        tmp_path / "usr-local" / "libexec" / "repair_release_venv.sh",
    )
    environment = helper_environment(
        installation,
        {
            "KNXOH_INSTALL_DIR": str(installation["install"]),
            "KNXOH_DATA_DIR": str(installation["data"]),
        },
    )

    result = subprocess.run(
        ["bash", str(stable_helper)],
        cwd=installation["install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert os.access(installation["release"] / "venv" / "bin" / "python", os.X_OK)
    assert not installation["helper"].exists()


def test_repair_revalidates_current_after_lock_acquisition(tmp_path):
    installation = create_install(tmp_path)
    current = installation["install"] / "current"
    other_release = installation["install"] / "releases" / "other"
    other_release.mkdir()
    (other_release / "requirements.txt").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "knxoh_paths.py", other_release / "knxoh_paths.py")
    (other_release / "web_ui" / "backend").mkdir(parents=True)
    (other_release / "web_ui" / "__init__.py").write_text("", encoding="utf-8")
    (other_release / "web_ui" / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (other_release / "web_ui" / "backend" / "auth.py").write_text(
        "def is_password_hash(value):\n    return bool(value)\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_flock = fake_bin / "flock"
    fake_flock.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-n" && "${2:-}" == "9" ]]; then\n'
        '  rm -- "$RACE_CURRENT_LINK"\n'
        '  ln -s -- "$RACE_NEXT_RELEASE" "$RACE_CURRENT_LINK"\n'
        "fi\n"
        'exec /usr/bin/flock "$@"\n',
        encoding="utf-8",
    )
    fake_flock.chmod(0o755)
    environment = helper_environment(
        installation,
        {
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "RACE_CURRENT_LINK": str(current),
            "RACE_NEXT_RELEASE": str(other_release),
        },
    )

    result = run_helper(installation, environment)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "no longer the active current release" in (result.stdout + result.stderr)
    assert current.resolve() == other_release.resolve()
    assert not (installation["release"] / "venv").exists()


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
    installation["helper"].unlink()
    stable_helper = install_stable_helper(
        installation,
        tmp_path / "stable libexec" / "repair_release_venv.sh",
    )
    release = installation["release"]
    (release / "version.json").write_text(
        '{"release_tag":"v1.2.3","commit_hash":"' + "a" * 40 + '"}\n',
        encoding="utf-8",
    )
    active_update = release / "update.sh"
    update_script = (ROOT / "update.sh").read_text(encoding="utf-8")
    update_script = update_script.replace(
        'VENV_REPAIR_HELPER="/usr/local/libexec/knx_to_openhab/repair_release_venv.sh"',
        f'VENV_REPAIR_HELPER="{stable_helper}"',
    )
    active_update.write_text(update_script, encoding="utf-8")
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
        "  args=()\n"
        '  for arg in "$@"; do\n'
        '    if [[ "$arg" == "/usr/local/libexec/knx_to_openhab/repair_release_venv.sh" ]]; then\n'
        '      arg="$TEST_STABLE_HELPER"\n'
        "    fi\n"
        '    args+=("$arg")\n'
        "  done\n"
        "  exec env -u KNXOH_INSTALL_DIR -u KNXOH_DATA_DIR "
        "-u KNXOH_MAINTENANCE_LOCK_FILE -u KNXOH_PATHS_FILE "
        '-u KNXOH_EXPECTED_RELEASE "${args[@]}"\n'
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
            "TEST_STABLE_HELPER": str(stable_helper),
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
        "env",
        f"KNXOH_INSTALL_DIR={installation['install']}",
        f"KNXOH_DATA_DIR={installation['data']}",
        f"KNXOH_MAINTENANCE_LOCK_FILE={installation['data'] / 'maintenance.lock'}",
        f"KNXOH_PATHS_FILE={installation['paths_file']}",
        f"KNXOH_EXPECTED_RELEASE={installation['release']}",
        "bash",
        str(stable_helper),
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


def test_recovery_command_preserves_custom_paths_under_sudo(tmp_path):
    installation = create_install(tmp_path)
    installation["helper"].unlink()
    stable_helper = install_stable_helper(
        installation,
        tmp_path / "stable libexec" / "repair_release_venv.sh",
    )
    active_update = installation["release"] / "update.sh"
    update_script = (ROOT / "update.sh").read_text(encoding="utf-8")
    update_script = update_script.replace(
        'VENV_REPAIR_HELPER="/usr/local/libexec/knx_to_openhab/repair_release_venv.sh"',
        f'VENV_REPAIR_HELPER="{stable_helper}"',
    )
    active_update.write_text(update_script, encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-n" && "${2:-}" == "-l" ]]; then\n'
        '  echo "NOPASSWD: limited service commands"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-u" && "${2:-}" == "knxohui" ]]; then\n'
        "  shift 2\n"
        "  args=()\n"
        '  for arg in "$@"; do\n'
        '    if [[ "$arg" == "/usr/local/libexec/knx_to_openhab/repair_release_venv.sh" ]]; then\n'
        '      arg="$TEST_STABLE_HELPER"\n'
        "    fi\n"
        '    args+=("$arg")\n'
        "  done\n"
        "  exec env -u KNXOH_INSTALL_DIR -u KNXOH_DATA_DIR "
        "-u KNXOH_MAINTENANCE_LOCK_FILE -u KNXOH_PATHS_FILE "
        '-u KNXOH_EXPECTED_RELEASE "${args[@]}"\n'
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    environment = helper_environment(
        installation,
        {
            "PATH": (
                f"{fake_bin}{os.pathsep}{installation['fake_bin']}"
                f"{os.pathsep}{os.environ['PATH']}"
            ),
            "KNXOH_INSTALL_DIR": str(installation["install"]),
            "KNXOH_DATA_DIR": str(installation["data"]),
            "KNXOH_CONFIG_DIR": str(tmp_path / "configuration"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "backups"),
            "LOG_FILE": str(tmp_path / "update.log"),
            "RELEASE_TAG": "v1.2.3",
            "RELEASE_COMMIT_HASH": "a" * 40,
            "TEST_STABLE_HELPER": str(stable_helper),
        },
    )

    update_text = active_update.read_text(encoding="utf-8")
    assert str(stable_helper) in update_text

    update_result = subprocess.run(
        ["bash", str(active_update)],
        cwd=installation["install"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert update_result.returncode == 1, update_result.stdout + update_result.stderr
    recovery_line = next(
        (line for line in update_result.stdout.splitlines() if "Recovery: run " in line), ""
    )
    assert recovery_line, update_result.stdout + update_result.stderr
    command = recovery_line.split("Recovery: run ", 1)[1].split(" from ", 1)[0].strip(" '\"")
    command_args = shlex.split(command)
    assert command_args == [
        "sudo",
        "-u",
        "knxohui",
        "env",
        f"KNXOH_INSTALL_DIR={installation['install']}",
        f"KNXOH_DATA_DIR={installation['data']}",
        f"KNXOH_MAINTENANCE_LOCK_FILE={installation['data'] / 'maintenance.lock'}",
        f"KNXOH_PATHS_FILE={installation['paths_file']}",
        f"KNXOH_EXPECTED_RELEASE={installation['release']}",
        "bash",
        str(stable_helper),
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
