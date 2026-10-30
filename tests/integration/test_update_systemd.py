"""OPT-IN acceptance on an already provisioned disposable systemd guest ONLY.

This file never creates users, installs policy/units, or boots/provisions a guest.
See README.md. Default collection must not contact a service manager.
"""

import json
import os
import re
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import pytest

from installer.update_core.systemd import SERVICES, SystemdAdapter


def _root_process():
    return os.name == "posix" and os.geteuid() == 0


def _read_attestation(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate disposable attestation field")
            value[key] = item
        return value

    raw = path.read_text()
    if len(raw.encode("utf-8")) > 4096:
        raise ValueError("Oversized disposable attestation")
    return json.loads(raw, object_pairs_hook=unique)


def _boot_uuid(value):
    if not isinstance(value, str):
        raise ValueError("Expected a canonical nonzero boot UUID")
    parsed = UUID(value)
    if str(parsed) != value or not parsed.int:
        raise ValueError("Expected a canonical nonzero boot UUID")
    return value


def _validate_attestations(env, marker, settings, machine_id, boot_id):
    if type(marker) is not dict or set(marker) != {"disposable", "machine_id", "nonce"}:
        raise ValueError("Invalid disposable marker schema")
    if type(settings) is not dict or set(settings) != {
        "nonce",
        "paths_file",
        "prior_boot_id",
        "offline_lock_absent",
    }:
        raise ValueError("Invalid disposable configuration schema")
    if marker["disposable"] is not True or settings["offline_lock_absent"] is not True:
        raise ValueError("Explicit disposable/offline attestations required")
    nonces = (env.get("KNXOH_DISPOSABLE_SYSTEMD_NONCE"), marker["nonce"], settings["nonce"])
    if any(not isinstance(n, str) or re.fullmatch(r"[0-9a-f]{64}", n) is None for n in nonces):
        raise ValueError("Explicit nonce must be 64 lowercase hexadecimal characters")
    if len(set(nonces)) != 1:
        raise ValueError("Disposable nonces disagree")
    if (
        not isinstance(machine_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", machine_id) is None
        or not int(machine_id, 16)
        or marker["machine_id"] != machine_id
    ):
        raise ValueError("Disposable machine identity mismatch")
    if _boot_uuid(settings["prior_boot_id"]) == _boot_uuid(boot_id):
        raise ValueError("A different real boot identity is required")
    path = settings["paths_file"]
    if (
        not isinstance(path, str)
        or not PurePosixPath(path).is_absolute()
        or str(PurePosixPath(path)) != path
        or ".." in PurePosixPath(path).parts
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
    ):
        raise ValueError("Expected a canonical absolute paths file")


def _check_worker_policy():
    # Trusted read-only provisioning checks, OUTSIDE the NoNewPrivileges child.
    # Listing permissions is not permission to execute a sudo action as worker.
    from installer.update_bootstrap import check_worker, check_worker_sudo

    check_worker()
    check_worker_sudo()


def _kernel_release():
    # Independent of detect-virt's choice of virtualization layer. Missing or
    # empty kernel evidence must not select the generic-provider fallback.
    value = Path("/proc/sys/kernel/osrelease").read_text().strip()
    if not value:
        raise ValueError("Missing kernel release evidence")
    return value


def _read_provider_receipt(path, *, fs=None):
    # Reuse the existing trusted POSIX traversal, not a new production loader.
    # Every ancestor is root-owned/non-writable and no-follow opened; directory
    # entries and the one opened regular leaf are pinned until after the read.
    if fs is None:
        from installer.update_core import secure_fs as fs
    from scripts.nested_acceptance import decode_receipt

    with fs._parent(path) as (stack, parent, name, chain):
        entry = fs._open(stack, parent, name, {0}, fs.os.fstat(parent).st_dev)
        if stat.S_IMODE(entry.info.st_mode) != 0o600 or entry.info.st_size > 4096:
            raise ValueError("Provider receipt must be bounded root-only data")
        raw = bytearray()
        while len(raw) <= 4096:
            chunk = fs.os.read(entry.fd, 4097 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        fs._check([*chain, entry])
        after = fs.os.fstat(entry.fd)
        fields = ("st_size", "st_mtime_ns", "st_ctime_ns")
        if len(raw) > 4096 or any(getattr(entry.info, f) != getattr(after, f) for f in fields):
            raise ValueError("Oversized or changed provider receipt")
    return decode_receipt(raw.decode("utf-8"))


def _check_virtualization(virt, nonce):
    assert virt not in ("", "none"), "nonvirtual host is forbidden"
    kernel = _kernel_release().casefold()
    selected = os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_PROVIDER")
    if selected not in (None, "fresh-wsl2-nspawn"):
        raise ValueError("Unknown explicit disposable provider")
    receipt_path = Path("/etc/knxoh-nested-acceptance.json")
    try:
        receipt_path.lstat()  # presence includes broken links; authentication is below
    except FileNotFoundError:
        marked = False
    else:
        marked = True
    if not (virt == "wsl" or "microsoft" in kernel or "wsl" in kernel or selected or marked):
        return
    # WSL's detect-virt result masks nested nspawn. Never admit ordinary WSL:
    # require the explicit fresh-import receipt PLUS live nested PID-1/mount
    # evidence. The Windows preflight independently checks outer identity and
    # disabled integration. Neither these checks nor the receipt prove that
    # sandbox properties actually took effect: runtime probes remain required.
    from scripts.nested_acceptance import validate_inner

    receipt = _read_provider_receipt(receipt_path)
    assert receipt["nonce"] == nonce
    validate_inner(
        receipt,
        {
            "machine_id": Path("/etc/machine-id").read_text().strip(),
            "pid1": Path("/proc/1/comm").read_text().strip(),
            "container": Path("/run/systemd/container").read_text().strip(),
            "pid1_container": next(
                (
                    v.split("=", 1)[1]
                    for v in Path("/proc/1/environ").read_text().split("\0")
                    if v.startswith("container=")
                ),
                "",
            ),
            "mounts": Path("/proc/self/mountinfo").read_text(),
            "interop": Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists(),
        },
    )


@pytest.fixture(scope="module")
def disposable():
    configured = os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_CONFIG")
    if not configured:
        pytest.skip("NOT VERIFIED: opt-in disposable systemd guest not configured")
    assert (
        os.environ.get("KNXOH_DISPOSABLE_SYSTEMD") == "destroy-this-guest"
    ), "explicit opt-in required"
    assert _root_process()
    # This marker belongs to the disposable image, NOT a marker supplied in /tmp
    # by the test caller. Bind it to this guest identity and an independent nonce.
    marker = Path("/etc/knxoh-disposable-systemd-test.json")
    info = marker.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
    value = _read_attestation(marker)
    config = Path(configured)
    info = config.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    settings = _read_attestation(config)
    _validate_attestations(
        os.environ,
        value,
        settings,
        Path("/etc/machine-id").read_text().strip(),
        Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    )
    virt = subprocess.run(["systemd-detect-virt"], capture_output=True, text=True, check=True)
    _check_virtualization(virt.stdout.strip(), value["nonce"])
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    _check_worker_policy()
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


def _sample_hostile_processes(unit, candidate):
    """Read-only live evidence; no candidate instrumentation or root execution."""
    cgroup = "/system.slice/" + unit
    try:
        pids = (Path("/sys/fs/cgroup" + cgroup) / "cgroup.procs").read_text().split()
    except FileNotFoundError:
        return {}  # not yet started or already torn down; never sufficient proof
    samples = {}
    for pid in pids:
        proc = Path("/proc") / pid
        try:
            argv = proc.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
            # Do not mistake systemd's pre-exec root setup task for installed
            # helper/candidate execution. Missing actual exec evidence fails below.
            if not any(
                path in argv
                for path in (
                    "/usr/local/libexec/knx_to_openhab/update_prepare.py",
                    str(candidate / "installer/config_migrations.py"),
                )
            ):
                continue
            status = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines())
            assert "0::" + cgroup in (proc / "cgroup").read_text().splitlines()
            samples[int(pid)] = dict(
                uid=[int(value) for value in status["Uid"].split()],
                gid=[int(value) for value in status["Gid"].split()],
                nnp=status["NoNewPrivs"].strip(),
                caps=[
                    int(status[key], 16)
                    for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
                ],
                mnt=os.readlink(proc / "ns/mnt"),
                net=os.readlink(proc / "ns/net"),
                observer_mnt=os.readlink("/proc/self/ns/mnt"),
                observer_net=os.readlink("/proc/self/ns/net"),
                interfaces=[
                    line.split(":", 1)[0].strip()
                    for line in (proc / "net/dev").read_text().splitlines()[2:]
                ],
                ipv4_routes=(proc / "net/route").read_text().splitlines()[1:],
                ipv6_interfaces=[
                    line.split()[-1]
                    for name in ("ipv6_route", "if_inet6")
                    for line in (proc / "net" / name).read_text().splitlines()
                ],
                argv=argv,
                sigign=int(status["SigIgn"], 16),
            )
        except (FileNotFoundError, ProcessLookupError):
            continue  # process exit race; a missing sample cannot establish PASS
    return samples


def _assert_hostile_process(proof, worker):
    assert proof["uid"] == [worker.pw_uid] * 4
    assert proof["gid"] == [worker.pw_gid] * 4
    assert proof["nnp"] == "1" and proof["caps"] == [0] * 5
    for namespace in ("mnt", "net"):
        assert proof[namespace] and proof["observer_" + namespace]
        assert proof[namespace] != proof["observer_" + namespace]
    assert proof["interfaces"] == ["lo"] and proof["ipv4_routes"] == []
    assert set(proof["ipv6_interfaces"]) <= {"lo"}


def test_real_migration_child_no_live_state_sudo_or_surviving_writer(disposable):
    import pwd

    from installer.update_core.protocol import Limits
    from installer.update_core.systemd import _path

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
        # This fixture intentionally forces a FAILED operation, not a successful
        # migration. Keep the production adapter fail-closed and collect live
        # evidence while it waits for the normal 15s SIGTERM/SIGKILL teardown.
        observed = {}
        unit = adapter._unit("migrate")
        with ThreadPoolExecutor(max_workers=1) as pool:
            child = pool.submit(adapter.run_child, "migrate", paths, workspace, candidate)
            while not child.done():
                for pid, proof in _sample_hostile_processes(unit, candidate).items():
                    if pid not in observed:
                        print("HOSTILE live evidence", pid, json.dumps(proof), flush=True)
                    _assert_hostile_process(proof, worker)
                    observed[pid] = proof
                time.sleep(0.02)
            # No generic CalledProcessError suppression: only the exact owned
            # systemd-run failure plus ALL independent evidence below may pass.
            with pytest.raises(subprocess.CalledProcessError) as failed:
                child.result()
        error = failed.value
        assert error.returncode == 1
        assert error.cmd[:4] == ["/usr/bin/systemd-run", "--wait", "--quiet", "--unit=" + unit]
        assert error.cmd[-9:] == [
            "--",
            "/usr/bin/python3",
            "-I",
            "/usr/local/libexec/knx_to_openhab/update_prepare.py",
            "migrate",
            "--workspace",
            _path(workspace),
            "--candidate",
            _path(candidate),
        ]
        assert "migrate" in adapter.stopped
        expected = dict(
            Id=unit,
            LoadState="loaded",
            ActiveState="failed",
            SubState="failed",
            Result="timeout",
            ExecMainCode="1",
            ExecMainStatus="0",
            ControlGroup="",
            MainPID="0",
            ControlPID="0",
            TimeoutStopUSec="15s",
        )
        final = show(unit, *expected)
        print("HOSTILE final unit evidence", json.dumps(final), flush=True)
        assert final == expected
        assert not Path("/sys/fs/cgroup/system.slice/" + unit).exists()
        assert observed, "Missing live worker/namespace evidence"
        assert any(
            "/usr/local/libexec/knx_to_openhab/update_prepare.py" in proof["argv"]
            for proof in observed.values()
        ), "Missing installed helper execution evidence"
        journal = subprocess.run(
            ["journalctl", "-b", "--no-pager", "-o", "json", "--unit=" + unit],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        killed = set()
        for line in journal.stdout.splitlines():
            entry = json.loads(line)
            match = re.search(
                r"Killing process ([0-9]+) .* with signal SIGKILL\.", entry.get("MESSAGE", "")
            )
            if entry.get("_PID") == "1" and entry.get("UNIT") == unit and match:
                killed.add(int(match[1]))
        # Link systemd's real SIGKILL to the observed candidate fork which ignored
        # SIGTERM, not a different unit/PID or a property-only SendSIGKILL claim.
        assert any(
            pid in killed and proof["sigign"] & (1 << 14) and str(script) in proof["argv"]
            for pid, proof in observed.items()
        ), "Missing own SIGTERM-ignoring candidate SIGKILL evidence"
        assert all(not Path("/proc/" + str(pid)).exists() for pid in observed)
        assert (output / "probe.json").stat().st_size < Limits.CONFIG_BYTES
        probe = json.loads((output / "probe.json").read_text())
        assert probe["uid"] == worker.pw_uid
        assert probe["denied"] == [
            str(paths.config_dir / "config.json"),
            str(paths.config_dir / "secrets.env"),
            str(paths.data_dir),
            str(paths.backup_dir),
            str(paths.config_dir / ".updater-state"),
        ]
        assert type(probe["sudo"]) is int and probe["sudo"] != 0
        heartbeat = (output / "heartbeat").read_bytes()
        assert heartbeat, "Missing heartbeat evidence"
        time.sleep(0.2)
        assert (output / "heartbeat").read_bytes() == heartbeat
        print(
            "HOSTILE termination evidence",
            json.dumps(
                dict(
                    observed=observed,
                    sigkill_pids=sorted(killed),
                    observed_pids_absent=True,
                    cgroup_absent=True,
                    probe=probe,
                    heartbeat_stable=True,
                    heartbeat_bytes=len(heartbeat),
                )
            ),
            flush=True,
        )
    finally:
        adapter.stop_children(request_id)
    assert adapter.stopped == {"metadata", "download", "extract", "dependencies", "migrate"}
    print("HOSTILE expected operation failure; confinement/termination PASS", flush=True)
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
