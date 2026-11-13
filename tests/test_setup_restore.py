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
