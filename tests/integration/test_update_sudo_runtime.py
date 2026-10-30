"""Read-only live provisioning regression; no grants/commands are executed.

Opt in only in the approved nested fixture AFTER Windows provider preflight.
This test intentionally exposes baseline 27d106a's refusal of Ubuntu sudo's
exit-0 complete-denial listing. It is NOT full application acceptance.
"""

import os
import re
import subprocess

import pytest


def test_live_complete_worker_denial_is_accepted_by_bootstrap():
    nonce = os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_NONCE")
    if os.environ.get("KNXOH_LIVE_SUDO_ACCEPTANCE") != "own-nested-read-only":
        pytest.skip("opt-in own-nested read-only sudo regression not configured")
    import test_update_systemd as harness

    from installer import update_bootstrap as admin

    assert harness._root_process()
    harness._check_virtualization("systemd-nspawn", nonce)
    admin.check_worker()
    result = subprocess.run(
        ["/usr/bin/sudo", "-n", "-l", "-U", "knxohupdate"],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    assert result.returncode in (0, 1)
    assert re.fullmatch(
        r"User knxohupdate is not allowed to run sudo on [^\r\n]+\.\n?",
        result.stdout + result.stderr,
    ), "real policy must explicitly deny ALL worker grants before testing bootstrap"
    print(f"Actual distro complete-denial listing exit: {result.returncode}")
    # Not mocked: repeats the production root query in this real guest. Baseline
    # incorrectly refuses an exit-0 listing containing only complete denial.
    admin.check_worker_sudo()
