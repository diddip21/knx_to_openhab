"""Top-level installer reports the failure code from setup."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bash") is None,
    reason="installer exit-code checks require Linux and Bash",
)


@pytest.mark.parametrize("setup_status", [2, 4])
def test_setup_failure_code_reaches_installer_caller(tmp_path, setup_status):
    install_dir = tmp_path / "install"
    setup_dir = install_dir / "installer"
    setup_dir.mkdir(parents=True)
    (setup_dir / "setup.sh").write_text(f"#!/bin/bash\nexit {setup_status}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["KNXOH_INSTALL_DIR"] = str(install_dir)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; INSTALL_DIR="$2"; run_setup_script',
            "exit-code-test",
            str(INSTALLER),
            str(install_dir),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == setup_status
    assert f"Setup script failed (status {setup_status})" in result.stdout + result.stderr
