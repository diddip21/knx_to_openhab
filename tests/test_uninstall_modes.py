import os
import select
import shutil
import subprocess
from pathlib import Path

import pytest

if os.name == "posix":
    import pty
else:
    pty = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
UNINSTALLER = ROOT / "uninstall.sh"

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="uninstaller shell integration tests require a POSIX Bash environment",
)


def create_fixture(tmp_path):
    root = tmp_path / "test-root"
    app = root / "custom install"
    config = root / "configuration"
    data = root / "runtime"
    backups = root / "backups"
    for directory in (app / "installer", config, data, backups):
        directory.mkdir(parents=True, exist_ok=True)
    (app / "installer" / "setup.sh").write_text("# fixture\n", encoding="utf-8")
    (config / "config.json").write_text('{"preserve": true}\n', encoding="utf-8")
    (data / "jobs.json").write_text('{"job": "preserve"}\n', encoding="utf-8")
    (backups / "keep.zip").write_bytes(b"backup")

    paths_file = config / "paths.env"
    path_values = {
        "KNXOH_INSTALL_DIR": app,
        "KNXOH_CONFIG_DIR": config,
        "KNXOH_DATA_DIR": data,
        "KNXOH_BACKUP_DIR": backups,
    }
    path_file_contents = "# managed paths\n" + "\n".join(
        f'{name}="{path}"' for name, path in path_values.items()
    )
    paths_file.write_text(path_file_contents + "\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo_log = tmp_path / "sudo.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        """#!/usr/bin/env bash
set -u
printf '%s\\0' "$@" >> "$SUDO_LOG"
printf '\\0' >> "$SUDO_LOG"
case "${1:-}" in
  systemctl)
    case "${2:-}" in
      is-active) [[ "${FAKE_ACTIVE:-0}" == 1 ]] && exit 0 || exit 3 ;;
      is-enabled) exit 1 ;;
      stop) [[ "${FAKE_STOP_FAIL:-0}" != 1 ]] || exit 1 ;;
    esac
    ;;
  rm)
    shift
    options=()
    while (($#)) && [[ "$1" != -- ]]; do options+=("$1"); shift; done
    [[ "${1:-}" == -- ]] && shift
    for target in "$@"; do
      case "$target" in
        "$SAFE_ROOT"/*) /bin/rm "${options[@]}" -- "$target" ;;
      esac
    done
    ;;
  userdel|groupdel) ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    fake_getent = fake_bin / "getent"
    fake_getent.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "${FAKE_SERVICE_ACCOUNT:-0}" == 1 && "${1:-}" =~ ^(passwd|group)$ '
        '&& "${2:-}" == knxohui ]]\n',
        encoding="utf-8",
    )
    fake_getent.chmod(0o755)

    environment = os.environ.copy()
    for key in (
        "KNXOH_INSTALL_DIR",
        "KNXOH_CONFIG_DIR",
        "KNXOH_DATA_DIR",
        "KNXOH_BACKUP_DIR",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_PATHS_FILE": str(paths_file),
            "SAFE_ROOT": str(root),
            "SUDO_LOG": str(sudo_log),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        }
    )
    return environment, app, config, data, backups, paths_file, sudo_log


def run_uninstaller(environment, args=(), *, input_text=None):
    return subprocess.run(
        ["bash", str(UNINSTALLER), *args],
        env=environment,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def sudo_arguments(log_path):
    if not log_path.exists():
        return []
    return [entry.decode() for entry in log_path.read_bytes().split(b"\0") if entry]


def test_help_and_unknown_option_do_not_call_sudo(tmp_path):
    environment, _, _, _, _, _, sudo_log = create_fixture(tmp_path)

    help_result = run_uninstaller(environment, ["--help"])
    unknown_result = run_uninstaller(environment, ["--unknown"])

    assert help_result.returncode == 0
    assert "--purge" in help_result.stdout
    assert unknown_result.returncode == 2
    assert "Unknown option" in unknown_result.stderr
    assert not sudo_log.exists()


def test_noninteractive_default_requires_yes_before_any_system_call(tmp_path):
    environment, app, config, data, backups, _, sudo_log = create_fixture(tmp_path)

    result = run_uninstaller(environment)

    assert result.returncode == 2
    assert "Non-interactive use requires --yes" in result.stderr
    assert all(path.exists() for path in (app, config, data, backups))
    assert not sudo_log.exists()


def test_noninteractive_purge_requires_yes_before_any_system_call(tmp_path):
    environment, app, config, data, backups, _, sudo_log = create_fixture(tmp_path)

    result = run_uninstaller(environment, ["--purge"])

    assert result.returncode == 2
    assert "Non-interactive purge requires --purge --yes" in result.stderr
    assert all(path.exists() for path in (app, config, data, backups))
    assert not sudo_log.exists()


def test_normal_uninstall_removes_app_but_preserves_user_data(tmp_path):
    environment, app, config, data, backups, paths_file, sudo_log = create_fixture(tmp_path)

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    assert paths_file.exists()
    assert (config / "config.json").exists()
    assert (data / "jobs.json").exists()
    assert (backups / "keep.zip").read_bytes() == b"backup"
    calls = sudo_arguments(sudo_log)
    assert "userdel" not in calls
    assert "groupdel" not in calls
    assert "Erhalten bleiben" in result.stdout


def test_purge_removes_custom_paths_and_service_account_and_can_repeat(tmp_path):
    environment, app, config, data, backups, _, sudo_log = create_fixture(tmp_path)
    environment["FAKE_SERVICE_ACCOUNT"] = "1"

    result = run_uninstaller(environment, ["--purge", "--yes"])

    assert result.returncode == 0, result.stderr
    assert all(not path.exists() for path in (app, config, data, backups))
    calls = sudo_arguments(sudo_log)
    assert "userdel" in calls
    assert "groupdel" in calls
    assert "Purge löscht zusätzlich" in result.stdout

    sudo_log.unlink()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(app),
            "KNXOH_CONFIG_DIR": str(config),
            "KNXOH_DATA_DIR": str(data),
            "KNXOH_BACKUP_DIR": str(backups),
        }
    )
    repeated = run_uninstaller(environment, ["--purge", "--yes"])

    assert repeated.returncode == 0, repeated.stderr
    assert "bereits entfernt" in repeated.stdout
    assert not sudo_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="A POSIX terminal is required")
@pytest.mark.parametrize(("confirmation", "expected_status"), [("PURGE", 0), ("purge", 2)])
def test_interactive_purge_requires_exact_confirmation(tmp_path, confirmation, expected_status):
    environment, _, _, _, _, _, sudo_log = create_fixture(tmp_path)
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        ["bash", str(UNINSTALLER), "--purge"],
        env=environment,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    os.write(master_fd, f"{confirmation}\n".encode())
    output = bytearray()
    while process.poll() is None:
        readable, _, _ = select.select([master_fd], [], [], 0.2)
        if readable:
            try:
                output.extend(os.read(master_fd, 4096))
            except OSError:
                break
    readable, _, _ = select.select([master_fd], [], [], 0.2)
    if readable:
        try:
            output.extend(os.read(master_fd, 4096))
        except OSError:
            pass
    process.wait(timeout=10)
    os.close(master_fd)

    assert process.returncode == expected_status, output.decode(errors="replace")
    assert b"exakt PURGE" in output
    assert sudo_log.exists() is (expected_status == 0)


def test_paths_file_is_data_and_not_shell_executed(tmp_path):
    environment, app, _, _, _, paths_file, sudo_log = create_fixture(tmp_path)
    marker = tmp_path / "shell-was-executed"
    content = paths_file.read_text(encoding="utf-8").replace(str(app), f"$(touch {marker})", 1)
    paths_file.write_text(content, encoding="utf-8")

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 2, result.stdout + result.stderr
    assert not marker.exists()
    assert not sudo_log.exists()


@pytest.mark.parametrize("unsafe_path", ["/", "/var/lib", "/opt/../etc"])
def test_broad_or_traversal_path_is_rejected_before_sudo(tmp_path, unsafe_path):
    environment, _, _, _, _, paths_file, sudo_log = create_fixture(tmp_path)
    contents = paths_file.read_text(encoding="utf-8").replace(
        'KNXOH_DATA_DIR="' + str(tmp_path / "test-root" / "runtime") + '"',
        f'KNXOH_DATA_DIR="{unsafe_path}"',
    )
    paths_file.write_text(contents, encoding="utf-8")

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 2
    assert "path" in result.stderr.lower() or "refusing" in result.stderr.lower()
    assert not sudo_log.exists()


def test_overlapping_or_symlinked_paths_are_rejected_before_sudo(tmp_path):
    environment, app, _, _, _, paths_file, sudo_log = create_fixture(tmp_path)
    contents = paths_file.read_text(encoding="utf-8").replace(
        str(tmp_path / "test-root" / "configuration"), str(app / "config"), 1
    )
    paths_file.write_text(contents, encoding="utf-8")
    overlap = run_uninstaller(environment, ["--yes"])
    assert overlap.returncode == 2
    assert "overlap" in overlap.stderr
    assert not sudo_log.exists()

    link = tmp_path / "linked-install"
    link.symlink_to(app, target_is_directory=True)
    contents = paths_file.read_text(encoding="utf-8").replace(str(app), str(link), 1)
    paths_file.write_text(contents, encoding="utf-8")
    symlink = run_uninstaller(environment, ["--yes"])
    assert symlink.returncode == 2
    assert "symlink" in symlink.stderr
    assert not sudo_log.exists()


def test_purge_refuses_a_regular_file_as_a_managed_directory(tmp_path):
    environment, _, _, data, _, paths_file, sudo_log = create_fixture(tmp_path)
    invalid_target = tmp_path / "test-root" / "runtime-file"
    invalid_target.write_text("keep this file", encoding="utf-8")
    contents = paths_file.read_text(encoding="utf-8").replace(str(data), str(invalid_target), 1)
    paths_file.write_text(contents, encoding="utf-8")

    result = run_uninstaller(environment, ["--purge", "--yes"])

    assert result.returncode == 2
    assert "not a directory" in result.stderr
    assert invalid_target.read_text(encoding="utf-8") == "keep this file"
    assert not sudo_log.exists()


def test_failed_service_stop_prevents_file_removal(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    environment["FAKE_ACTIVE"] = "1"
    environment["FAKE_STOP_FAIL"] = "1"

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode != 0
    assert app.exists()
    calls = sudo_arguments(sudo_log)
    assert "stop" in calls
    assert "rm" not in calls
