"""Regression tests for setup's systemd updater quiescing guard."""

import fcntl
import os
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUIESCE_SCRIPT = ROOT / "installer" / "quiesce_update_service.sh"
QUIESCE_UNIT_SCRIPT = ROOT / "installer" / "quiesce_systemd_unit.sh"
SETUP_MAINTENANCE_SCRIPT = ROOT / "installer" / "setup_maintenance.sh"
INSTALL_UPDATE_UNIT_SCRIPT = ROOT / "installer" / "install_update_unit.sh"
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
    first_app_mutation = setup.index('sudo mkdir -p "$BASE"')
    rsync_mutation = setup.index("sudo rsync -a")
    stop_services = setup.index('sudo bash "$REPO_ROOT/installer/quiesce_systemd_unit.sh"')
    updater_quiescence = setup.index('sudo bash "$REPO_ROOT/installer/quiesce_update_service.sh"')
    release_for_restart = setup.index(
        "release_maintenance_lock", setup.index("sudo systemctl daemon-reload")
    )
    restart = setup.index("sudo systemctl restart knxohui.service")

    assert stop_services < updater_quiescence < lock_setup < first_app_mutation < rsync_mutation
    assert release_for_restart < restart

    trap_body = setup[
        setup.index("restore_previous_services() {") : setup.index(
            "trap restore_previous_services EXIT"
        )
    ]
    assert trap_body.index("release_maintenance_lock") < trap_body.index(
        'sudo systemctl start "$unit"'
    )
    assert "mask_update_service_for_setup" not in setup
    assert "unmask_update_service_after_setup" not in setup


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
                'source "$1"; quiesce() { echo quiesced >> "$SETUP_QUIESCE_LOG"; }; '
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
        ["bash", str(INSTALL_UPDATE_UNIT_SCRIPT), str(unit_source), str(destination)],
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
        ["bash", str(INSTALL_UPDATE_UNIT_SCRIPT), str(unit_source), str(destination)],
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
