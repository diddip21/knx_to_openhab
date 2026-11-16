"""Existing service accounts must be compatible before setup changes ownership."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "installer" / "validate_service_identity.sh"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bash") is None,
    reason="service account validation requires Linux and Bash",
)


@pytest.mark.parametrize(
    ("account", "group", "expected_status", "expected_message"),
    [
        ("", "", 0, ""),
        ("knxohui:x:997:997::/nonexistent:/usr/sbin/nologin", "knxohui:x:997:", 0, ""),
        (
            "knxohui:x:997:998::/nonexistent:/usr/sbin/nologin",
            "knxohui:x:997:",
            2,
            "matching service group",
        ),
        (
            "knxohui:x:997:997::/home/knxohui:/bin/bash",
            "knxohui:x:997:",
            2,
            "interactive or unknown login shell",
        ),
        ("knxohui:x:997:997::/nonexistent:/usr/sbin/nologin", "", 2, "no matching service group"),
    ],
)
def test_existing_service_account_is_checked_before_setup(
    tmp_path, account, group, expected_status, expected_message
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    getent = fake_bin / "getent"
    getent.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  passwd) [ -n "$TEST_ACCOUNT" ] || exit 2; printf "%s\\n" "$TEST_ACCOUNT" ;;\n'
        '  group) [ -n "$TEST_GROUP" ] || exit 2; printf "%s\\n" "$TEST_GROUP" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    getent.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "TEST_ACCOUNT": account,
            "TEST_GROUP": group,
        }
    )

    result = subprocess.run(
        ["bash", str(CHECK), "knxohui"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == expected_status, result.stdout + result.stderr
    assert expected_message in result.stderr


def test_account_lookup_error_stops_setup(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    getent = fake_bin / "getent"
    getent.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    getent.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        ["bash", str(CHECK), "knxohui"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Could not look up" in result.stderr


def test_setup_checks_service_identity_before_privileged_changes():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    validation = setup.index('bash "$REPO_ROOT/installer/validate_service_identity.sh"')
    group_creation = setup.index('sudo groupadd -r "$SERVICE_USER"')
    service_quiescence = setup.index(
        'echo "Stopping services and waiting for the updater to finish"'
    )

    assert validation < group_creation < service_quiescence
