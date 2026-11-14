"""Exercise setup's real service-stop and failure-restoration path in isolation."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is required")


def test_setup_failure_restores_previous_service_and_preserves_data(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "service.state"
    state.write_text("active\n", encoding="utf-8")
    events = tmp_path / "events.log"
    user_data = tmp_path / "user-data.json"
    user_data.write_text('{"custom":"keep"}\n', encoding="utf-8")

    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[[ "${1:-}" == systemctl ]] || exit 2\n'
        "shift\n"
        'case "${1:-}" in\n'
        "  show)\n"
        '    if [[ "${2:-}" == --property=LoadState ]]; then echo loaded; '
        'else cat "$RESTORE_STATE"; fi ;;\n'
        "  list-jobs) ;;\n"
        '  stop) echo inactive > "$RESTORE_STATE"; echo stop >> "$RESTORE_EVENTS" ;;\n'
        '  daemon-reload) echo reload >> "$RESTORE_EVENTS" ;;\n'
        '  start) echo active > "$RESTORE_STATE"; echo start >> "$RESTORE_EVENTS" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "RESTORE_STATE": str(state),
            "RESTORE_EVENTS": str(events),
        }
    )

    script = (
        'source "$1"\n'
        'release_setup_updater_locks() { echo updater-unlock >> "$RESTORE_EVENTS"; }\n'
        'release_maintenance_lock() { echo maintenance-unlock >> "$RESTORE_EVENTS"; }\n'
        "PREVIOUSLY_ACTIVE_UNITS=(knxohui.service)\n"
        "SETUP_COMPLETED=0\n"
        "trap restore_previous_services EXIT\n"
        'bash "$2" knxohui.service || exit $?\n'
        '[[ "$(cat "$RESTORE_STATE")" == inactive ]] || exit 90\n'
        "exit 23\n"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            script,
            "setup-restore-test",
            str(ROOT / "installer" / "setup_restore.sh"),
            str(ROOT / "installer" / "quiesce_systemd_unit.sh"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 23, result.stdout + result.stderr
    assert state.read_text(encoding="utf-8").strip() == "active"
    assert user_data.read_text(encoding="utf-8") == '{"custom":"keep"}\n'
    assert events.read_text(encoding="utf-8").splitlines() == [
        "stop",
        "updater-unlock",
        "maintenance-unlock",
        "reload",
        "start",
    ]


@pytest.mark.parametrize("exit_status", [0, 23])
def test_setup_restore_cleans_up_staged_bind_config(tmp_path, exit_status):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == rm && "$2" == -f && "$3" == -- ]] || exit 2\n'
        'shift 3; /bin/rm -f -- "$@"\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    staged = tmp_path / "config.json.knxoh-preflight.test"
    staged.write_text('{"bind_host":"127.0.0.1"}\n', encoding="utf-8")
    existing = tmp_path / "config.json"
    existing.write_text('{"bind_host":"192.0.2.10"}\n', encoding="utf-8")
    script = (
        'set -euo pipefail\n'
        'source "$1"\n'
        'release_setup_updater_locks() { :; }\n'
        'release_maintenance_lock() { :; }\n'
        'PREVIOUSLY_ACTIVE_UNITS=()\n'
        'SETUP_COMPLETED=0\n'
        'BIND_PREFLIGHT_CONFIG="$2"\n'
        'trap restore_previous_services EXIT\n'
        'exit "$3"\n'
    )
    result = subprocess.run(
        [
            "bash", "-c", script, "cleanup-test",
            str(ROOT / "installer/setup_restore.sh"), str(staged), str(exit_status),
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == exit_status, result.stdout + result.stderr
    assert not staged.exists()
    assert existing.read_text(encoding="utf-8") == '{"bind_host":"192.0.2.10"}\n'
