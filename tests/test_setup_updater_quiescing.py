"""Regression tests for setup's systemd updater quiescing guard."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUIESCE_SCRIPT = ROOT / "installer" / "quiesce_update_service.sh"
UPDATER_UNIT = "knxohui-update.service"


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
    fake_bin.mkdir()
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


def test_quiesce_accepts_an_uninstalled_updater_unit(tmp_path):
    result, events = run_quiescer(tmp_path, load_state="not-found")

    assert result.returncode == 0, result.stdout + result.stderr
    assert events == [f"show --property=LoadState --value {UPDATER_UNIT}"]


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

    web_ui_stop = setup.index("stop_unit_if_active knxohui.service")
    quiesce_call = setup.index('sudo bash "$REPO_ROOT/installer/quiesce_update_service.sh"')
    first_mutation = setup.index('sudo groupadd -r "$SERVICE_USER"')
    assert web_ui_stop < quiesce_call < first_mutation
    assert quiesce_call < setup.index('sudo python3 -m venv "$BASE/venv"')
    assert quiesce_call < setup.index("sudo rsync -a")
