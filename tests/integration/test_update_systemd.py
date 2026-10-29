"""OPT-IN acceptance on an already provisioned disposable systemd guest ONLY.

This file never creates users, installs policy/units, or boots/provisions a guest.
See README.md. Default collection must not contact a service manager.
"""

import json
import os
import stat
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from installer.update_core.systemd import SERVICES, SystemdAdapter


@pytest.fixture(scope="module")
def disposable():
    configured = os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_CONFIG")
    if not configured:
        pytest.skip("NOT VERIFIED: opt-in disposable systemd guest not configured")
    assert (
        os.environ.get("KNXOH_DISPOSABLE_SYSTEMD") == "destroy-this-guest"
    ), "explicit opt-in required"
    assert os.name == "posix" and os.geteuid() == 0
    # This marker belongs to the disposable image, NOT a marker supplied in /tmp
    # by the test caller. Bind it to this guest identity and an independent nonce.
    marker = Path("/etc/knxoh-disposable-systemd-test.json")
    info = marker.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
    value = json.loads(marker.read_text())
    assert value["disposable"] is True
    assert value["machine_id"] == Path("/etc/machine-id").read_text().strip()
    assert value["nonce"] == os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_NONCE")
    virt = subprocess.run(["systemd-detect-virt"], capture_output=True, text=True, check=True)
    assert virt.stdout.strip() not in ("", "none", "wsl"), "development WSL/host is forbidden"
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    config = Path(configured)
    info = config.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    settings = json.loads(config.read_text())
    assert settings["nonce"] == value["nonce"]
    assert settings["prior_boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert settings["offline_lock_absent"] is True
    from installer.update_core.transaction import load_paths

    paths = load_paths(Path(settings["paths_file"]))
    # Require custom-path/spaces coverage instead of silently testing defaults.
    assert all(
        " " in str(p) for p in (paths.releases, paths.config_dir, paths.data_dir, paths.backup_dir)
    )
    return settings, paths


def show(unit, *properties):
    result = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            "--all",
            *("--property=" + p for p in properties),
            "--",
            unit,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def test_real_boot_tmpfiles_recovery_writer_order_and_no_cycle(disposable):
    _settings, _paths = disposable
    lock = Path("/run/lock/knxohui-lifecycle.lock").lstat()
    assert (lock.st_uid, lock.st_gid, stat.S_IMODE(lock.st_mode)) == (0, 0, 0o600)
    recovery = show(
        "knxohui-update-recovery.service",
        "ActiveState",
        "SubState",
        "Result",
        "ActiveEnterTimestampMonotonic",
        "After",
        "Requires",
    )
    assert recovery["ActiveState"] == "active" and recovery["SubState"] == "exited"
    assert recovery["Result"] == "success"
    for key in ("After", "Requires"):
        assert "systemd-tmpfiles-setup.service" in recovery[key].split()
    tmpfiles = show("systemd-tmpfiles-setup.service", "ActiveEnterTimestampMonotonic")
    assert int(tmpfiles["ActiveEnterTimestampMonotonic"]) <= int(
        recovery["ActiveEnterTimestampMonotonic"]
    )
    for unit in SERVICES:
        writer = show(
            unit,
            "After",
            "Requires",
            "ActiveEnterTimestampMonotonic",
            "ExecMainStartTimestampMonotonic",
        )
        assert "knxohui-update-recovery.service" in writer["After"].split()
        assert "knxohui-update-recovery.service" in writer["Requires"].split()
        timestamp = (
            "ExecMainStartTimestampMonotonic"
            if unit.endswith("cleanup.service")
            else "ActiveEnterTimestampMonotonic"
        )
        assert int(writer[timestamp]) >= int(recovery["ActiveEnterTimestampMonotonic"]) > 0
    ui = show(SERVICES[0], "Type", "ActiveState", "SubState")
    assert ui == {"Type": "notify", "ActiveState": "active", "SubState": "running"}
    journal = subprocess.run(
        ["journalctl", "-b", "--no-pager", "-p", "warning"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "ordering cycle" not in journal.stdout.lower()


def test_real_migration_child_no_live_state_sudo_or_surviving_writer(disposable):
    import pwd

    from installer.update_core.protocol import Limits

    _settings, paths = disposable
    worker = pwd.getpwnam("knxohupdate")
    assert worker.pw_uid != 0 and worker.pw_shell in ("/usr/sbin/nologin", "/sbin/nologin")
    request_id = str(uuid4())
    root = Path("/var/lib/knxohupdate-preparation") / ("acceptance-" + request_id)
    root.mkdir(mode=0o750)
    os.chown(root, 0, worker.pw_gid)
    workspace = root / "migrate"
    workspace.mkdir(mode=0o750)
    os.chown(workspace, 0, worker.pw_gid)
    output = workspace / "output"
    output.mkdir(mode=0o700)
    os.chown(output, worker.pw_uid, worker.pw_gid)
    (workspace / "input.json").write_text("{}")
    candidate = paths.releases / ("acceptance-" + request_id)
    candidate.mkdir(mode=0o755)
    (candidate / "installer").mkdir(mode=0o755)
    # This deliberately hostile fixture is candidate Python, run by the ACTUAL
    # installed update_prepare and ACTUAL transient sandbox, never root.
    script = candidate / "installer/config_migrations.py"
    script.write_text(
        "import json,os,signal,subprocess,time\nfrom pathlib import Path\n"
        f"output=Path({str(output)!r})\n"
        f"targets={[str(paths.config_dir / 'config.json'), str(paths.config_dir / 'secrets.env'), str(paths.data_dir), str(paths.backup_dir), str(paths.config_dir / '.updater-state')]!r}\n"
        "denied=[]\nfor target in targets:\n"
        " try:\n  p=Path(target)\n  list(p.iterdir()) if p.is_dir() else p.read_bytes()\n"
        " except (PermissionError,FileNotFoundError): denied.append(target)\n"
        "sudo=subprocess.run(['/usr/bin/sudo','-n','/usr/bin/id'],capture_output=True,timeout=5)\n"
        "(output/'probe.json').write_text(json.dumps(dict(uid=os.geteuid(),denied=denied,sudo=sudo.returncode)))\n"
        "pid=os.fork()\nif pid==0:\n"
        " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        " while True:\n  (output/'heartbeat').write_text(str(time.monotonic_ns()))\n  time.sleep(.02)\n"
        "time.sleep(.1)\n"
    )
    adapter = SystemdAdapter(request_id)
    try:
        adapter.run_child("migrate", paths, workspace, candidate)
    finally:
        adapter.stop_children(request_id)
    assert adapter.stopped == {"metadata", "download", "extract", "dependencies", "migrate"}
    probe = json.loads((output / "probe.json").read_text())
    assert probe["uid"] == worker.pw_uid and len(probe["denied"]) == 5
    assert probe["sudo"] != 0
    heartbeat = (output / "heartbeat").read_bytes()
    time.sleep(0.2)
    assert (output / "heartbeat").read_bytes() == heartbeat
    assert (output / "probe.json").stat().st_size < Limits.CONFIG_BYTES
    # Retain this guest's evidence for review; destroy the whole guest afterward.


def test_real_failed_recovery_blocks_both_writer_units(disposable):
    _settings, paths = disposable
    journal = paths.config_dir / ".updater-state/journal.json"
    original = journal.read_bytes() if journal.exists() else None
    units = [*SERVICES, "knxohui-update.service", "knxohui-update-recovery.service"]

    def control(action, names, check=True):
        return subprocess.run(
            ["/usr/bin/systemctl", action, "--", *names],
            check=check,
            capture_output=True,
            text=True,
            timeout=60,
        )

    try:
        control("stop", units)
        journal.write_bytes(b"{corrupt-disposable-acceptance-journal")
        journal.chmod(0o600)
        for writer in SERVICES:
            result = control("start", [writer], check=False)
            assert result.returncode != 0
            assert show(writer, "ActiveState")["ActiveState"] in ("inactive", "failed")
        assert show("knxohui-update-recovery.service", "Result")["Result"] != "success"
    finally:
        control("stop", units)
        if original is None:
            journal.unlink()
        else:
            journal.write_bytes(original)
        control("reset-failed", units)
        control("start", list(SERVICES))
