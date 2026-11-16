"""Regression tests for setup's systemd updater quiescing guard."""

import fcntl
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUIESCE_SCRIPT = ROOT / "installer" / "quiesce_update_service.sh"
QUIESCE_UNIT_SCRIPT = ROOT / "installer" / "quiesce_systemd_unit.sh"
SETUP_MAINTENANCE_SCRIPT = ROOT / "installer" / "setup_maintenance.sh"
SETUP_SYSTEMD_UNIT_HELPER = ROOT / "installer" / "setup_systemd_unit.sh"
UPDATER_LOCK_HOLDER_SCRIPT = ROOT / "installer" / "hold_updater_locks.sh"
UPDATER_UNIT = "knxohui-update.service"


def run_under_exclusive_maintenance_lock(tmp_path, command, environment):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    environment = os.environ.copy() | environment
    environment["KNXOH_MAINTENANCE_LOCK_FILE"] = str(lock_file)
    with lock_file.open("r+") as lock_stream:
        fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    return result


def test_updater_lock_holder_retains_multiple_locks_until_stopped(tmp_path):
    lock_files = [tmp_path / "old-data" / "updater.lock", tmp_path / "new-data" / "updater.lock"]
    for lock_file in lock_files:
        lock_file.parent.mkdir()

    process = subprocess.Popen(
        ["bash", str(UPDATER_LOCK_HOLDER_SCRIPT), *(str(path) for path in lock_files)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        readiness = process.stdout.readline().strip()
        assert readiness.startswith("LOCKED ")
        for lock_file in lock_files:
            with lock_file.open("a") as probe:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        process.terminate()
        _stdout, _stderr = process.communicate(timeout=5)

    for lock_file in lock_files:
        with lock_file.open("a") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_updater_lock_holder_releases_partial_locks_when_one_is_busy(tmp_path):
    first_lock = tmp_path / "first-updater.lock"
    busy_lock = tmp_path / "busy-updater.lock"
    first_lock.touch()
    busy_lock.touch()

    with busy_lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            ["bash", str(UPDATER_LOCK_HOLDER_SCRIPT), str(first_lock), str(busy_lock)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert result.returncode == 75
    with first_lock.open("a") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_setup_updater_guard_holds_old_and_selected_data_locks(tmp_path):
    lock_files = [
        tmp_path / "previous-data" / "updater.lock",
        tmp_path / "selected-data" / "updater.lock",
    ]
    for lock_file in lock_files:
        lock_file.parent.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/usr/bin/env bash\n[[ "${1:-}" != -u ]] || shift 2\nexec "$@"\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    process = subprocess.Popen(
        [
            "bash",
            "-c",
            'source "$1"; acquire_setup_updater_locks knxohui "$2" "$3" || exit $?; '
            "echo LOCKS_HELD; IFS= read -r _; release_setup_updater_locks",
            "setup-updater-lock-test",
            str(SETUP_MAINTENANCE_SCRIPT),
            str(lock_files[0]),
            str(lock_files[1]),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        assert process.stdout.readline().strip() == "LOCKS_HELD"
        for lock_file in lock_files:
            with lock_file.open("a") as probe:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        stdout, stderr = process.communicate(input="release\n", timeout=10)

    assert process.returncode == 0, stdout + stderr
    for lock_file in lock_files:
        with lock_file.open("a") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)


def run_quiescer(
    tmp_path,
    *,
    load_state="loaded",
    active_mode="inactive",
    pending=False,
    cancel_fail=False,
    timeout_seconds=None,
):
    fake_bin = tmp_path / "fake bin"
    fake_bin.mkdir(parents=True)
    log_file = tmp_path / "systemctl.log"
    query_count = tmp_path / "active-query-count"
    pending_file = tmp_path / "pending-job"
    if pending:
        pending_file.write_text("pending\n", encoding="utf-8")

    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "${1:-}" == systemctl ]] || exit 2\n'
        "shift\n"
        'printf \'%s\\n\' "$*" >> "$QUIESCE_TEST_LOG"\n'
        'case "${1:-}" in\n'
        "  show)\n"
        '    if [[ "${2:-}" == --property=LoadState ]]; then\n'
        '      echo "$QUIESCE_TEST_LOAD_STATE"\n'
        '    elif [[ "${2:-}" == --property=ActiveState ]]; then\n'
        '      case "$QUIESCE_TEST_ACTIVE_MODE" in\n'
        "        active-then-inactive)\n"
        '          if [[ -f "$QUIESCE_TEST_QUERY_COUNT" ]]; then\n'
        "            echo inactive\n"
        "          else\n"
        '            : > "$QUIESCE_TEST_QUERY_COUNT"\n'
        "            echo active\n"
        "          fi\n"
        "          ;;\n"
        "        error) exit 9 ;;\n"
        '        *) echo "$QUIESCE_TEST_ACTIVE_MODE" ;;\n'
        "      esac\n"
        "    else\n"
        "      exit 2\n"
        "    fi\n"
        "    ;;\n"
        "  list-jobs)\n"
        '    if [[ -s "$QUIESCE_TEST_PENDING_FILE" ]]; then\n'
        "      printf '77 %s start waiting\\n' \"$QUIESCE_TEST_UNIT\"\n"
        "    fi\n"
        "    ;;\n"
        "  cancel)\n"
        '    [[ "${2:-}" == 77 ]] || exit 3\n'
        '    [[ "$QUIESCE_TEST_CANCEL_FAIL" != 1 ]] || exit 8\n'
        '    : > "$QUIESCE_TEST_PENDING_FILE"\n'
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "QUIESCE_TEST_LOG": str(log_file),
            "QUIESCE_TEST_QUERY_COUNT": str(query_count),
            "QUIESCE_TEST_PENDING_FILE": str(pending_file),
            "QUIESCE_TEST_LOAD_STATE": load_state,
            "QUIESCE_TEST_ACTIVE_MODE": active_mode,
            "QUIESCE_TEST_UNIT": UPDATER_UNIT,
            "QUIESCE_TEST_CANCEL_FAIL": "1" if cancel_fail else "0",
        }
    )
    if timeout_seconds is not None:
        environment["KNXOH_SETUP_UPDATER_QUIESCE_TIMEOUT_SECONDS"] = str(timeout_seconds)
    result = subprocess.run(
        ["bash", str(QUIESCE_SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    events = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    return result, events


def run_unit_quiescer(
    tmp_path,
    *,
    load_state="loaded",
    active_state="inactive",
    jobs="",
    stop_fail=False,
    cancel_fail=False,
    fail_inspection="",
):
    fake_bin = tmp_path / "unit fake bin"
    fake_bin.mkdir(parents=True)
    log_file = tmp_path / "unit-systemctl.log"
    state_file = tmp_path / "unit-active-state"
    jobs_file = tmp_path / "unit-jobs"
    state_file.write_text(active_state, encoding="utf-8")
    jobs_file.write_text(jobs, encoding="utf-8")
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "${1:-}" == systemctl ]] || exit 2\n'
        "shift\n"
        'printf \'%s\\n\' "$*" >> "$UNIT_TEST_LOG"\n'
        'case "${1:-}" in\n'
        "  show)\n"
        '    [[ "$UNIT_TEST_FAIL_INSPECTION" != load ]] || exit 7\n'
        '    case "${2:-}" in\n'
        "      --property=LoadState) printf '%s\\n' \"$UNIT_TEST_LOAD_STATE\" ;;\n"
        '      --property=ActiveState) cat "$UNIT_TEST_STATE_FILE" ;;\n'
        "      *) exit 2 ;;\n"
        "    esac\n"
        "    ;;\n"
        '  stop) [[ "$UNIT_TEST_STOP_FAIL" != 1 ]] || exit 8; printf inactive > "$UNIT_TEST_STATE_FILE" ;;\n'
        '  list-jobs) [[ "$UNIT_TEST_FAIL_INSPECTION" != jobs ]] || exit 7; cat "$UNIT_TEST_JOBS_FILE" ;;\n'
        '  cancel) [[ "$UNIT_TEST_CANCEL_FAIL" != 1 ]] || exit 9; : > "$UNIT_TEST_JOBS_FILE" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "UNIT_TEST_LOG": str(log_file),
            "UNIT_TEST_STATE_FILE": str(state_file),
            "UNIT_TEST_JOBS_FILE": str(jobs_file),
            "UNIT_TEST_LOAD_STATE": load_state,
            "UNIT_TEST_STOP_FAIL": "1" if stop_fail else "0",
            "UNIT_TEST_CANCEL_FAIL": "1" if cancel_fail else "0",
            "UNIT_TEST_FAIL_INSPECTION": fail_inspection,
        }
    )
    result = subprocess.run(
        ["bash", str(QUIESCE_UNIT_SCRIPT), "example.service"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    events = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    return result, events


def test_quiesce_waits_for_active_updater_to_finish(tmp_path):
    result, events = run_quiescer(tmp_path, active_mode="active-then-inactive")

    assert result.returncode == 0, result.stdout + result.stderr
    assert any("--property=ActiveState" in event for event in events)
    assert events[-1].startswith("list-jobs ")


def test_quiesce_cancels_a_queued_updater_start(tmp_path):
    result, events = run_quiescer(tmp_path, pending=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "cancel 77" in events
    assert events.index("cancel 77") < max(
        index for index, event in enumerate(events) if event.startswith("list-jobs ")
    )


def test_quiesce_checks_state_and_jobs_for_an_uninstalled_updater_unit(tmp_path):
    result, events = run_quiescer(tmp_path, load_state="not-found")

    assert result.returncode == 0, result.stdout + result.stderr
    assert events[0] == f"show --property=LoadState --value {UPDATER_UNIT}"
    assert f"show --property=ActiveState --value {UPDATER_UNIT}" in events
    assert sum(event.startswith("list-jobs ") for event in events) == 2


def test_quiesce_waits_for_a_retained_active_uninstalled_updater_unit(tmp_path):
    result, events = run_quiescer(
        tmp_path,
        load_state="not-found",
        active_mode="active-then-inactive",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    active_queries = [event for event in events if "--property=ActiveState" in event]
    assert len(active_queries) >= 3


def test_quiesce_cancels_a_queued_start_for_an_uninstalled_updater_unit(tmp_path):
    result, events = run_quiescer(tmp_path, load_state="not-found", pending=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "cancel 77" in events
    assert any("--property=ActiveState" in event for event in events)
    assert sum(event.startswith("list-jobs ") for event in events) >= 2


@pytest.mark.parametrize(
    ("active_mode", "expected_message"),
    [("error", "Could not inspect"), ("unknown-state", "Unknown updater state")],
)
def test_quiesce_fails_closed_on_unknown_or_unreadable_state(
    tmp_path, active_mode, expected_message
):
    result, _ = run_quiescer(tmp_path, active_mode=active_mode)

    assert result.returncode != 0
    assert expected_message in result.stderr


def test_quiesce_fails_closed_when_a_queued_job_cannot_be_cancelled(tmp_path):
    result, _ = run_quiescer(tmp_path, pending=True, cancel_fail=True)

    assert result.returncode != 0
    assert "Could not cancel pending updater job 77" in result.stderr


def test_quiesce_fails_closed_when_updater_does_not_finish_before_timeout(tmp_path):
    result, _ = run_quiescer(tmp_path, active_mode="active", timeout_seconds=0)

    assert result.returncode != 0
    assert "Timed out waiting for the updater to quiesce" in result.stderr


def test_setup_quiesces_updater_after_web_ui_stop_and_before_mutations():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    lock_setup = setup.index("acquire_setup_maintenance_lock")
    stable_helper_install = setup.index(
        "sudo install -d -o root -g root -m 0755 /usr/local/libexec"
    )
    tmpfiles_write = setup.index("write_maintenance_lock_tmpfiles.py")
    tmpfiles_create = setup.index("systemd-tmpfiles --create")
    first_app_mutation = setup.index('sudo mkdir -p "$BASE"')
    rsync_mutation = setup.index("sudo rsync -a")
    stop_services = setup.index('sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh"')
    updater_quiescence = setup.index('sudo bash "$REPO_ROOT/installer/quiesce_update_service.sh"')
    unit_installation = setup.index(
        'install_setup_systemd_unit "$REPO_ROOT/installer/knxohui.service"'
    )
    daemon_reload = setup.index("sudo systemctl daemon-reload", unit_installation)
    service_enable = setup.index("setup_systemctl_if_unmasked knxohui.service enable")
    timer_enable = setup.index("setup_systemctl_if_unmasked knxohui-backup-cleanup.timer enable")
    release_for_restart = setup.index("release_maintenance_lock", daemon_reload)
    restart = setup.index("setup_systemctl_if_unmasked knxohui.service restart")
    timer_start = setup.index("setup_systemctl_if_unmasked knxohui-backup-cleanup.timer start")

    assert stop_services < updater_quiescence < lock_setup < first_app_mutation < rsync_mutation
    assert lock_setup < stable_helper_install < tmpfiles_write < tmpfiles_create
    assert rsync_mutation < unit_installation < daemon_reload
    assert daemon_reload < service_enable < timer_enable < release_for_restart
    assert release_for_restart < restart
    assert release_for_restart < timer_start

    assert 'source "$SCRIPT_DIR/setup_restore.sh"' in setup
    trap_body = (ROOT / "installer" / "setup_restore.sh").read_text(encoding="utf-8")
    assert trap_body.index("release_maintenance_lock") < trap_body.index(
        'sudo systemctl start "$unit"'
    )
    assert "mask_update_service_for_setup" not in setup
    assert "unmask_update_service_after_setup" not in setup


def test_setup_requiesces_units_after_replacing_legacy_launch_helpers():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    lock_acquisition = setup.index("acquire_setup_maintenance_lock quiesce_setup_services")
    helpers_installed = setup.index(
        'sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/launch_update.sh"'
    )
    tmpfiles_created = setup.index("systemd-tmpfiles --create")
    final_quiescence = setup.index("quiesce_setup_services", tmpfiles_created)
    first_app_mutation = setup.index('sudo mkdir -p "$BASE"')

    assert lock_acquisition < helpers_installed < tmpfiles_created < final_quiescence
    assert final_quiescence < first_app_mutation


def test_setup_holds_saved_and_selected_updater_locks_before_mutations():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    maintenance_acquisition = setup.index("acquire_setup_maintenance_lock quiesce_setup_services")
    updater_acquisition = setup.index("acquire_setup_updater_locks")
    helper_installation = setup.index(
        'sudo install -o root -g root -m 0755 "$REPO_ROOT/installer/maintenance_lock.sh"'
    )
    first_app_mutation = setup.index('sudo mkdir -p "$BASE"')
    lock_release = setup.index("release_setup_updater_locks", first_app_mutation)
    service_restart = setup.index("setup_systemctl_if_unmasked knxohui.service restart")

    assert maintenance_acquisition < updater_acquisition < helper_installation
    assert helper_installation < first_app_mutation < lock_release < service_restart
    assert '"$SAVED_DATA_DIR/updater.lock"' in setup
    assert '"$DATA_DIR/updater.lock"' in setup
    assert 'SAVED_DATA_DIR="$(read_saved_path KNXOH_DATA_DIR /var/lib/knx_to_openhab)"' in setup
    assert '"KNXOH_SETUP_UPDATER_LOCK_HELD=1"' in setup


def test_setup_resolves_lock_path_before_system_account_mutations():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    resolver = setup.index('resolve_maintenance_lock_path "$PATHS_FILE" allow-initial')
    group_creation = setup.index('sudo groupadd -r "$SERVICE_USER"')
    user_creation = setup.index('sudo useradd -r -g "$SERVICE_USER"')

    assert resolver < group_creation
    assert resolver < user_creation


@pytest.mark.parametrize(
    ("load_state", "active_state", "jobs", "expected_event"),
    [
        ("loaded", "active", "", "stop example.service"),
        ("not-found", "active", "", "stop example.service"),
        ("not-found", "inactive", "77 example.service start waiting\n", "cancel 77"),
    ],
)
def test_generic_quiescer_handles_active_and_queued_units(
    tmp_path, load_state, active_state, jobs, expected_event
):
    result, events = run_unit_quiescer(
        tmp_path,
        load_state=load_state,
        active_state=active_state,
        jobs=jobs,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert expected_event in events
    expected_job_checks = 3 if expected_event.startswith("cancel ") else 2
    assert sum(event.startswith("list-jobs ") for event in events) == expected_job_checks


def test_unit_quiescer_stops_active_runtime_masked_unit(tmp_path):
    result, events = run_unit_quiescer(
        tmp_path,
        load_state="masked",
        active_state="active",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "stop example.service" in events
    assert events[-1] == "list-jobs --no-legend --no-pager example.service"


def test_generic_quiescer_fails_closed_when_stop_or_job_cancellation_fails(tmp_path):
    stop_result, _ = run_unit_quiescer(tmp_path / "stop", active_state="active", stop_fail=True)
    cancel_result, _ = run_unit_quiescer(
        tmp_path / "cancel",
        jobs="77 example.service start waiting\n",
        cancel_fail=True,
    )

    assert stop_result.returncode != 0
    assert "Could not stop" in stop_result.stderr
    assert cancel_result.returncode != 0
    assert "Could not cancel pending job 77" in cancel_result.stderr


@pytest.mark.parametrize("fail_inspection", ["load", "jobs"])
def test_generic_quiescer_fails_closed_when_systemd_inspection_fails(tmp_path, fail_inspection):
    result, _ = run_unit_quiescer(tmp_path, fail_inspection=fail_inspection)

    assert result.returncode != 0
    assert "Could not inspect" in result.stderr


def test_setup_maintenance_retries_quiescence_after_shared_lock_wins_race(tmp_path):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    quiesce_log = tmp_path / "quiesce.log"
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_MAINTENANCE_LOCK_FILE": str(lock_file),
            "KNXOH_SETUP_MAINTENANCE_TIMEOUT_SECONDS": "5",
            "SETUP_QUIESCE_LOG": str(quiesce_log),
        }
    )
    with lock_file.open("r+") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        process = subprocess.Popen(
            [
                "bash",
                "-c",
                'source "$1"; _validate_maintenance_lock_ancestors() { return 0; }; '
                'quiesce() { echo quiesced >> "$SETUP_QUIESCE_LOG"; }; '
                "acquire_setup_maintenance_lock quiesce && release_maintenance_lock",
                "maintenance-test",
                str(SETUP_MAINTENANCE_SCRIPT),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.poll() is None

        def release_after_contention():
            wait = threading.Event()
            for _ in range(400):
                if quiesce_log.exists() and len(quiesce_log.read_text().splitlines()) >= 2:
                    break
                wait.wait(0.01)
            fcntl.flock(holder, fcntl.LOCK_UN)

        release_holder = threading.Thread(target=release_after_contention)
        release_holder.start()
        stdout, stderr = process.communicate(timeout=10)
        release_holder.join(timeout=2)

    assert process.returncode == 0, stdout + stderr
    assert len(quiesce_log.read_text(encoding="utf-8").splitlines()) >= 3


def test_update_unit_installer_preserves_a_systemd_mask(tmp_path):
    fake_bin = tmp_path / "unit-install-bin"
    fake_bin.mkdir()
    log_file = tmp_path / "unit-install.log"
    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        '#!/bin/bash\n[[ "$1" == show ]] || exit 2\necho "$UNIT_INSTALL_LOAD_STATE"\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$UNIT_INSTALL_LOG"\nexec "$@"\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    unit_source = tmp_path / "source.service"
    unit_source.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    destination = tmp_path / "systemd" / "knxohui-update.service"
    destination.parent.mkdir()
    destination.symlink_to("/dev/null")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "UNIT_INSTALL_LOG": str(log_file),
            "UNIT_INSTALL_LOAD_STATE": "masked",
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; install_setup_systemd_unit "$2" "$3" knxohui-update.service',
            "unit-install-test",
            str(SETUP_SYSTEMD_UNIT_HELPER),
            str(unit_source),
            str(destination),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.is_symlink()
    assert os.readlink(destination) == "/dev/null"
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "systemctl show --property=LoadState --value knxohui-update.service"
    ]


def test_update_unit_installer_replaces_an_unmasked_unit(tmp_path):
    fake_bin = tmp_path / "unmasked-unit-install-bin"
    fake_bin.mkdir()
    log_file = tmp_path / "unmasked-unit-install.log"
    (fake_bin / "systemctl").write_text(
        '#!/bin/bash\n[[ "$1" == show ]] || exit 2\necho loaded\n', encoding="utf-8"
    )
    (fake_bin / "systemctl").chmod(0o755)
    (fake_bin / "sudo").write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$UNIT_INSTALL_LOG"\nexec "$@"\n',
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    unit_source = tmp_path / "new-update.service"
    unit_source.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    destination = tmp_path / "systemd" / "knxohui-update.service"
    destination.parent.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "UNIT_INSTALL_LOG": str(log_file),
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; install_setup_systemd_unit "$2" "$3" knxohui-update.service',
            "unit-install-test",
            str(SETUP_SYSTEMD_UNIT_HELPER),
            str(unit_source),
            str(destination),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.read_text(encoding="utf-8") == unit_source.read_text(encoding="utf-8")
    assert log_file.read_text(encoding="utf-8").splitlines()[-1].startswith("install ")


def test_web_launcher_fails_closed_while_setup_holds_exclusive_lock(tmp_path):
    install = tmp_path / "install"
    data = tmp_path / "data"
    executable = install / "current" / "venv" / "bin" / "gunicorn"
    marker = tmp_path / "web-started"
    executable.parent.mkdir(parents=True)
    data.mkdir()
    executable.write_text(f"#!/bin/bash\n: > {marker}\n", encoding="utf-8")
    executable.chmod(0o755)

    result = run_under_exclusive_maintenance_lock(
        tmp_path,
        ["bash", str(ROOT / "installer" / "launch_web.sh")],
        {
            "KNXOH_INSTALL_DIR": str(install),
            "KNXOH_DATA_DIR": str(data),
        },
    )

    assert result.returncode != 0
    assert "setup or uninstall is in progress" in (result.stdout + result.stderr).lower()
    assert not marker.exists()


def test_update_launcher_fails_closed_while_setup_holds_exclusive_lock(tmp_path):
    install = tmp_path / "install"
    python = install / "current" / "venv" / "bin" / "python"
    worker = install / "current" / "installer" / "run_update_request.py"
    marker = tmp_path / "update-started"
    python.parent.mkdir(parents=True)
    worker.parent.mkdir(parents=True)
    python.write_text(f"#!/bin/bash\n: > {marker}\n", encoding="utf-8")
    python.chmod(0o755)
    worker.write_text("# worker\n", encoding="utf-8")

    result = run_under_exclusive_maintenance_lock(
        tmp_path,
        ["bash", str(ROOT / "installer" / "launch_update.sh")],
        {"KNXOH_INSTALL_DIR": str(install)},
    )

    assert result.returncode != 0
    assert "setup or uninstall is in progress" in (result.stdout + result.stderr).lower()
    assert not marker.exists()


def test_backup_cleanup_launcher_fails_closed_while_setup_holds_exclusive_lock(tmp_path):
    install = tmp_path / "install"
    cleanup = install / "current" / "installer" / "backup_cleanup.sh"
    marker = tmp_path / "cleanup-started"
    cleanup.parent.mkdir(parents=True)
    cleanup.write_text(f"#!/bin/bash\n: > {marker}\n", encoding="utf-8")

    result = run_under_exclusive_maintenance_lock(
        tmp_path,
        ["bash", str(ROOT / "installer" / "launch_backup_cleanup.sh")],
        {"KNXOH_INSTALL_DIR": str(install)},
    )

    assert result.returncode != 0
    assert "setup or uninstall is in progress" in (result.stdout + result.stderr).lower()
    assert not marker.exists()


def test_backup_cleanup_launcher_waits_for_updates_to_release_the_updater_lock(tmp_path):
    install = tmp_path / "install"
    cleanup = install / "current" / "installer" / "backup_cleanup.sh"
    marker = tmp_path / "cleanup-started"
    cleanup.parent.mkdir(parents=True)
    cleanup.write_text(f"#!/bin/bash\n: > {marker}\n", encoding="utf-8")
    launcher_dir = tmp_path / "stable-launcher"
    launcher_dir.mkdir()
    shutil.copy2(ROOT / "installer" / "launch_backup_cleanup.sh", launcher_dir)
    maintenance_helper = launcher_dir / "maintenance_lock.sh"
    maintenance_helper.write_text(
        (ROOT / "installer" / "maintenance_lock.sh").read_text(encoding="utf-8")
        + "\n_validate_maintenance_lock_ancestors() { return 0; }\n",
        encoding="utf-8",
    )
    maintenance_lock = tmp_path / "maintenance.lock"
    maintenance_lock.touch()
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        f"# Managed by installer/setup.sh; do not edit by hand.\n"
        f'KNXOH_MAINTENANCE_LOCK_FILE="{maintenance_lock}"\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "runtime-data"
    data_dir.mkdir()
    updater_lock = data_dir / "updater.lock"
    updater_lock.touch()
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "KNXOH_MAINTENANCE_LOCK_FILE": str(maintenance_lock),
        }
    )

    with updater_lock.open("r+") as update_stream:
        fcntl.flock(update_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = subprocess.run(
            ["bash", str(launcher_dir / "launch_backup_cleanup.sh")],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    assert blocked.returncode != 0
    assert "update is in progress" in (blocked.stdout + blocked.stderr).lower()
    assert not marker.exists()

    retry = subprocess.run(
        ["bash", str(launcher_dir / "launch_backup_cleanup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert marker.is_file()


def test_direct_updater_fails_before_logging_while_setup_holds_exclusive_lock(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    log_file = tmp_path / "update.log"

    result = run_under_exclusive_maintenance_lock(
        tmp_path,
        ["bash", str(ROOT / "update.sh")],
        {
            "KNXOH_INSTALL_DIR": str(install),
            "RELEASE_TAG": "invalid",
            "LOG_FILE": str(log_file),
        },
    )

    assert result.returncode != 0
    assert "setup or uninstall is in progress" in (result.stdout + result.stderr).lower()
    assert not log_file.exists()
