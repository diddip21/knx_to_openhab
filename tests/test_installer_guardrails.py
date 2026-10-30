import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("system_path", ["/etc", "/usr", "/var", "/home"])
def test_setup_rejects_system_wide_application_directory_before_writes(tmp_path, system_path):
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": system_path,
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "KNXOH_DATA_DIR": str(tmp_path / "data"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "installer" / "setup.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"Refusing a system-wide path as application: {system_path}" in result.stderr


def test_setup_stops_service_before_migration_and_restarts_after_unit_reload():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    stop_index = setup.index("stop_unit_if_active knxohui.service")
    migration_index = setup.index("migrate_runtime_data.py")
    daemon_reload_index = setup.index("sudo systemctl daemon-reload", migration_index)
    restart_index = setup.index("sudo systemctl restart knxohui.service")

    assert stop_index < migration_index < daemon_reload_index < restart_index
    assert "sudo systemctl enable --now knxohui.service" not in setup
    assert 'sudo install -o root -g root -m 0755 "$BASE/installer/set_ui_password.py" ' in setup
