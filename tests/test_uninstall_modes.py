import fcntl
import os
import pty
import select
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNINSTALLER = ROOT / "uninstall.sh"
MAINTENANCE_HELPER = ROOT / "installer" / "maintenance_lock.sh"
QUIESCE_HELPER = ROOT / "installer" / "quiesce_systemd_unit.sh"
REMOVE_UNIT_HELPER = ROOT / "installer" / "uninstall_unit_files.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is required")


def test_uninstaller_removes_the_transactional_update_unit():
    content = UNINSTALLER.read_text(encoding="utf-8")

    assert "knxohui-update.service" in content
    assert "/etc/systemd/system/knxohui-update.service" in content
    assert content.index("knxohui.service") < content.index("knxohui-update.service")


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
    maintenance_lock = tmp_path / "maintenance.lock"
    maintenance_lock.touch()
    maintenance_lock.chmod(0o666)
    lock_check_log = tmp_path / "lock-check.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        """#!/usr/bin/env bash
set -u
printf '%s\\0' "$@" >> "$SUDO_LOG"
printf '\\0' >> "$SUDO_LOG"
case "${1:-}" in
  systemctl)
    case "${2:-}" in
      show)
        unit="${5:-}"
        if [[ "${3:-}" == --property=LoadState ]]; then
          if [[ "$unit" == "${FAKE_MISSING_UNIT:-}" ]]; then
            printf 'not-found\n'
          else
            printf 'loaded\n'
          fi
          exit 0
        fi
        if [[ "$unit" == knxohui-update.service && -n "${FAKE_SYSTEM_STATE_FILE:-}" \
          && -f "$FAKE_SYSTEM_STATE_FILE" ]]; then
          state=$(<"$FAKE_SYSTEM_STATE_FILE")
        elif [[ "$unit" == knxohui.service && "${FAKE_WEB_ACTIVE:-0}" == 1 ]]; then
          if [[ -n "${FAKE_WEB_STATE_FILE:-}" && -f "$FAKE_WEB_STATE_FILE" ]]; then
            state=$(<"$FAKE_WEB_STATE_FILE")
          else
            state=active
          fi
        elif [[ "${FAKE_ACTIVE:-0}" == 1 ]]; then
          state=active
        else
          state="${FAKE_ACTIVE_STATE:-inactive}"
        fi
        printf '%s\n' "$state"
        ;;
      list-jobs)
        if [[ -n "${FAKE_PENDING_START_FILE:-}" && -s "$FAKE_PENDING_START_FILE" ]]; then
          printf '1 knxohui-update.service start waiting\n'
        fi
        ;;
      is-active) [[ "${FAKE_ACTIVE:-0}" == 1 ]] && exit 0 || exit 3 ;;
      is-enabled)
        if [[ "${FAKE_CHECK_LOCK_ON_IS_ENABLED:-0}" == 1 ]]; then
          flock --shared --nonblock "$KNXOH_MAINTENANCE_LOCK_FILE" -c true \
            && printf 'unlocked\n' >> "$LOCK_CHECK_LOG" \
            || printf 'held\n' >> "$LOCK_CHECK_LOG"
        fi
        [[ "${FAKE_ENABLE_INSPECTION_FAIL:-0}" != 1 ]] || exit 7
        exit 1
        ;;
      stop)
        [[ "${FAKE_STOP_FAIL:-0}" != 1 ]] || exit 1
        [[ "${3:-}" != "${FAKE_MISSING_UNIT:-}" \
          || "${3:-}" == "${FAKE_RETAINED_ACTIVE_UNIT:-}" ]] || exit 5
        if [[ -n "${FAKE_SYSTEM_STATE_FILE:-}" ]]; then
          case "${3:-}" in
            knxohui-update.service)
              printf 'inactive\n' > "$FAKE_SYSTEM_STATE_FILE"
              [[ -z "${FAKE_PENDING_START_FILE:-}" ]] \
                || : > "$FAKE_PENDING_START_FILE"
              if [[ "${FAKE_START_WEB_WHEN_UPDATER_STOPS:-0}" == 1 \
                && -n "${FAKE_WEB_STATE_FILE:-}" ]]; then
                printf 'active\n' > "$FAKE_WEB_STATE_FILE"
              fi
              ;;
            knxohui.service)
              [[ -z "${FAKE_WEB_STATE_FILE:-}" ]] \
                || printf 'inactive\n' > "$FAKE_WEB_STATE_FILE"
              [[ "${FAKE_START_UPDATER_WHEN_WEB_STOPS:-0}" != 1 ]] \
                || printf 'activating\n' > "$FAKE_SYSTEM_STATE_FILE"
              ;;
          esac
        fi
        ;;
      cancel)
        [[ -z "${FAKE_PENDING_START_FILE:-}" ]] || : > "$FAKE_PENDING_START_FILE"
        ;;
    esac
    ;;
  flock)
    shift
    exec flock "$@"
    ;;
  kill) shift; exec /bin/kill "$@" ;;
  bash) shift; exec /bin/bash "$@" ;;
  rm)
    shift
    options=()
    while (($#)) && [[ "$1" != -- ]]; do options+=("$1"); shift; done
    [[ "${1:-}" == -- ]] && shift
    for target in "$@"; do
      case "$target" in
        "$SAFE_ROOT"/*)
          if [[ "${FAKE_CHECK_LOCK_ON_RM:-0}" == 1 ]]; then
            flock --shared --nonblock "$KNXOH_MAINTENANCE_LOCK_FILE" -c true \
              && printf 'unlocked\n' >> "$LOCK_CHECK_LOG" \
              || printf 'held\n' >> "$LOCK_CHECK_LOG"
          fi
          /bin/rm "${options[@]}" -- "$target"
          ;;
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
            "LOCK_CHECK_LOG": str(lock_check_log),
            "KNXOH_MAINTENANCE_LOCK_FILE": str(maintenance_lock),
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


def sudo_invocations(log_path):
    if not log_path.exists():
        return []
    return [
        [argument.decode() for argument in invocation.split(b"\0") if argument]
        for invocation in log_path.read_bytes().split(b"\0\0")
        if invocation
    ]


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


def test_uninstall_holds_exclusive_maintenance_lock_while_removing_files(tmp_path):
    environment, app, _, _, _, _, _ = create_fixture(tmp_path)
    lock_check_log = Path(environment["LOCK_CHECK_LOG"])
    environment["FAKE_CHECK_LOCK_ON_RM"] = "1"

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    assert lock_check_log.read_text(encoding="utf-8").splitlines()
    assert set(lock_check_log.read_text(encoding="utf-8").splitlines()) == {"held"}


def test_uninstall_releases_exclusive_lock_after_a_post_acquisition_failure(tmp_path):
    environment, app, _, _, _, _, _ = create_fixture(tmp_path)
    environment["FAKE_ENABLE_INSPECTION_FAIL"] = "1"
    environment["FAKE_CHECK_LOCK_ON_IS_ENABLED"] = "1"
    lock_file = Path(environment["KNXOH_MAINTENANCE_LOCK_FILE"])
    lock_check_log = Path(environment["LOCK_CHECK_LOG"])

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode != 0
    assert app.exists()
    assert lock_check_log.read_text(encoding="utf-8").splitlines() == ["held"]
    with lock_file.open("r+") as lock_stream:
        fcntl.flock(lock_stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(lock_stream, fcntl.LOCK_UN)


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


def test_uninstall_stops_updater_while_oneshot_unit_is_activating(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    state_file = tmp_path / "systemd-state"
    state_file.write_text("activating\n", encoding="utf-8")
    environment["FAKE_SYSTEM_STATE_FILE"] = str(state_file)

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    calls = sudo_arguments(sudo_log)
    assert "show" in calls
    assert calls.index("stop") < calls.index("rm")
    assert state_file.read_text(encoding="utf-8").strip() == "inactive"


def test_uninstall_aborts_on_unknown_updater_state_before_file_removal(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    environment["FAKE_ACTIVE_STATE"] = "unknown"

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode != 0
    assert "state" in result.stderr.lower()
    assert app.exists()
    assert "rm" not in sudo_arguments(sudo_log)


def test_uninstall_quiesces_web_service_before_final_updater_stop(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    state_file = tmp_path / "systemd-state"
    state_file.write_text("inactive\n", encoding="utf-8")
    web_state_file = tmp_path / "web-systemd-state"
    web_state_file.write_text("active\n", encoding="utf-8")
    environment.update(
        {
            "FAKE_SYSTEM_STATE_FILE": str(state_file),
            "FAKE_WEB_STATE_FILE": str(web_state_file),
            "FAKE_WEB_ACTIVE": "1",
            "FAKE_START_UPDATER_WHEN_WEB_STOPS": "1",
        }
    )

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    calls = sudo_arguments(sudo_log)
    update_state_check = calls.index("knxohui-update.service")
    assert calls.index("knxohui.service", calls.index("stop")) < update_state_check
    assert calls.index("stop", update_state_check) < calls.index("rm")
    assert state_file.read_text(encoding="utf-8").strip() == "inactive"


def test_uninstall_stops_web_ui_again_after_updater_restarts_it(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    state_file = tmp_path / "systemd-state"
    state_file.write_text("active\n", encoding="utf-8")
    web_state_file = tmp_path / "web-systemd-state"
    web_state_file.write_text("inactive\n", encoding="utf-8")
    environment.update(
        {
            "FAKE_SYSTEM_STATE_FILE": str(state_file),
            "FAKE_WEB_STATE_FILE": str(web_state_file),
            "FAKE_WEB_ACTIVE": "1",
            "FAKE_START_WEB_WHEN_UPDATER_STOPS": "1",
        }
    )

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    invocations = sudo_invocations(sudo_log)
    updater_stop = next(
        index
        for index, invocation in enumerate(invocations)
        if invocation[:3] == ["systemctl", "stop", "knxohui-update.service"]
    )
    web_stop_after_updater = next(
        index
        for index, invocation in enumerate(invocations)
        if index > updater_stop and invocation[:3] == ["systemctl", "stop", "knxohui.service"]
    )
    assert updater_stop < web_stop_after_updater
    assert web_state_file.read_text(encoding="utf-8").strip() == "inactive"


def test_uninstall_quiesces_a_retained_active_unit_with_not_found_fragment(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    state_file = tmp_path / "systemd-state"
    state_file.write_text("active\n", encoding="utf-8")
    environment.update(
        {
            "FAKE_SYSTEM_STATE_FILE": str(state_file),
            "FAKE_MISSING_UNIT": "knxohui-update.service",
            "FAKE_RETAINED_ACTIVE_UNIT": "knxohui-update.service",
        }
    )

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    assert state_file.read_text(encoding="utf-8").strip() == "inactive"
    invocations = sudo_invocations(sudo_log)
    assert any(
        invocation[:3] == ["systemctl", "show", "--property=ActiveState"]
        and invocation[-1] == "knxohui-update.service"
        for invocation in invocations
    )


def test_uninstall_cancels_pending_updater_start_when_state_is_inactive(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    state_file = tmp_path / "systemd-state"
    state_file.write_text("inactive\n", encoding="utf-8")
    pending_start_file = tmp_path / "pending-start"
    pending_start_file.write_text("queued\n", encoding="utf-8")
    environment.update(
        {
            "FAKE_SYSTEM_STATE_FILE": str(state_file),
            "FAKE_PENDING_START_FILE": str(pending_start_file),
        }
    )

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    invocations = sudo_invocations(sudo_log)
    cancel_index = next(
        index
        for index, invocation in enumerate(invocations)
        if invocation[:3] == ["systemctl", "cancel", "1"]
    )
    assert cancel_index < next(
        index for index, invocation in enumerate(invocations) if invocation[0] == "rm"
    )
    assert pending_start_file.read_text(encoding="utf-8") == ""


def test_uninstall_tolerates_unit_that_is_not_installed(tmp_path):
    environment, app, _, _, _, _, sudo_log = create_fixture(tmp_path)
    missing_unit = "knxohui-backup-cleanup.service"
    environment["FAKE_MISSING_UNIT"] = missing_unit

    result = run_uninstaller(environment, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert not app.exists()
    calls = sudo_arguments(sudo_log)
    assert missing_unit in calls
    missing_unit_index = calls.index(missing_unit)
    assert "stop" not in calls[missing_unit_index - 1 : missing_unit_index + 2]


def test_unit_removal_preserves_mask_symlinks_in_all_managed_unit_locations(tmp_path):
    environment, _, _, _, _, _, _ = create_fixture(tmp_path)
    root = Path(environment["SAFE_ROOT"])
    masks = [root / f"unit-{index}.service" for index in range(4)]
    masks.append(root / "tmpfiles.conf")
    regular = root / "regular.service"
    for mask in masks:
        mask.symlink_to("/dev/null")
    regular.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; for unit in "${@:2}"; do remove_unit_file_preserving_mask "$unit"; done',
            "unit-removal-test",
            str(REMOVE_UNIT_HELPER),
            *(str(path) for path in [*masks, regular]),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert all(mask.is_symlink() and os.readlink(mask) == "/dev/null" for mask in masks)
    assert not regular.exists()


def test_uninstall_retries_quiescence_when_shared_lock_wins_race(tmp_path):
    environment, _, _, _, _, _, sudo_log = create_fixture(tmp_path)
    lock_file = Path(environment["KNXOH_MAINTENANCE_LOCK_FILE"])
    with lock_file.open("r+") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        process = subprocess.Popen(
            ["bash", str(UNINSTALLER), "--yes"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def release_after_retry():
            wait = threading.Event()
            for _ in range(400):
                invocations = sudo_invocations(sudo_log)
                timer_checks = sum(
                    invocation[:3] == ["systemctl", "show", "--property=LoadState"]
                    and invocation[-1] == "knxohui-backup-cleanup.timer"
                    for invocation in invocations
                )
                if timer_checks >= 3:
                    break
                wait.wait(0.01)
            fcntl.flock(holder, fcntl.LOCK_UN)

        releaser = threading.Thread(target=release_after_retry)
        releaser.start()
        stdout, stderr = process.communicate(timeout=10)
        releaser.join(timeout=5)

    assert process.returncode == 0, stdout + stderr
