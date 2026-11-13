"""Repeated installer runs must not refresh package lists unnecessarily."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bash") is None,
    reason="the installer dependency check requires Linux and Bash",
)


def _run_dependency_step(tmp_path, missing_package=""):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    dpkg = fake_bin / "dpkg"
    dpkg.write_text(
        "#!/bin/bash\n"
        "for package in git python3 python3-venv python3-pip rsync curl; do\n"
        '  if [[ "$package" != "$MISSING_PACKAGE" ]]; then\n'
        '    printf "ii  %s 1.0 all installed\\n" "$package"\n'
        "  fi\n"
        "done\n",
        encoding="utf-8",
    )
    dpkg.chmod(0o755)
    sudo = fake_bin / "sudo"
    sudo.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$APT_CALLS"\n', encoding="utf-8")
    sudo.chmod(0o755)
    calls = tmp_path / "apt-calls"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "MISSING_PACKAGE": missing_package,
            "APT_CALLS": str(calls),
        }
    )
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; install_dependencies', "dependency-test", str(INSTALLER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, calls


def test_complete_package_set_skips_apt_update(tmp_path):
    result, calls = _run_dependency_step(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not calls.exists()


def test_missing_package_updates_index_once_before_install(tmp_path):
    result, calls = _run_dependency_step(tmp_path, missing_package="python3-venv")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "apt-get update -qq",
        "apt-get install -y -qq python3-venv",
    ]
