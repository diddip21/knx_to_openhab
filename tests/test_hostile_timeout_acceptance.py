"""Portable evidence replay of the hostile callback; NEVER contact a manager/guest."""

import copy
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from installer.update_core import systemd


@pytest.fixture
def replay(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "_offline_hostile_acceptance", Path(__file__).parent / "integration/test_update_systemd.py"
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    worker = SimpleNamespace(pw_uid=997, pw_gid=988, pw_shell="/usr/sbin/nologin")
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=lambda name: worker))
    monkeypatch.setattr(harness.os, "chown", lambda *args: None, raising=False)
    real_path = Path

    def mapped_path(value):
        if value == "/var/lib/knxohupdate-preparation":
            return tmp_path
        if (
            str(value).startswith("/sys/fs/cgroup/")
            or str(value) == "/proc"
            or str(value).startswith("/proc/")
        ):
            return tmp_path / "absent" / str(value).lstrip("/")
        return real_path(value)

    monkeypatch.setattr(harness, "Path", mapped_path)
    # Only the OS path encoding is replaced; run_child/_stop/stop_children and
    # their exceptions are REAL production code, not a success-returning adapter.
    monkeypatch.setattr(
        systemd, "_path", lambda path: "/offline/" + path.as_posix().replace(":", "")
    )
    releases = tmp_path / "releases"
    releases.mkdir()
    paths = SimpleNamespace(
        releases=releases,
        current=tmp_path / "current",
        config_dir=tmp_path / "live config",
        data_dir=tmp_path / "live data",
        backup_dir=tmp_path / "live backups",
    )
    state = SimpleNamespace(fault=None, calls=[], sampled=threading.Event(), adapter=None)

    def run(argv, **kwargs):
        state.calls.append(argv)
        if argv[0] == "/usr/bin/systemd-run":
            output = next(tmp_path.glob("acceptance-*/migrate/output"))
            denied = [
                str(paths.config_dir / "config.json"),
                str(paths.config_dir / "secrets.env"),
                str(paths.data_dir),
                str(paths.backup_dir),
                str(paths.config_dir / ".updater-state"),
            ]
            probe = dict(uid=998 if state.fault == "uid" else 997, denied=denied, sudo=1)
            if state.fault == "denied":
                probe["denied"][-1] = probe["denied"][0]
            if state.fault == "sudo":
                probe["sudo"] = 0
            (output / "probe.json").write_text(json.dumps(probe))
            if state.fault != "heartbeat":
                (output / "heartbeat").write_text("retained stopped heartbeat")
            if state.fault in ("alive", "cgroup-present"):
                path = (
                    "/proc/113150"
                    if state.fault == "alive"
                    else "/sys/fs/cgroup/system.slice/" + state.adapter._unit("migrate")
                )
                mapped_path(path).mkdir(parents=True)
            state.sampled.wait(0.2)
            if state.fault == "effect":
                raise OSError("effect failed")
            if state.fault == "unexpected-success":
                return subprocess.CompletedProcess(argv, 0)
            if state.fault == "unexpected-exit":
                raise subprocess.CalledProcessError(2, argv)
            if state.fault == "unrelated-error":
                raise subprocess.CalledProcessError(1, ["/usr/bin/systemctl", "show", "unrelated"])
            raise subprocess.CalledProcessError(1, argv)
        if argv[0] == "journalctl":
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    dict(
                        _PID="1",
                        UNIT=(
                            "unrelated"
                            if state.fault == "journal-unit"
                            else state.adapter._unit("migrate")
                        ),
                        MESSAGE=(
                            "Killing process 113151 (python3) with signal SIGKILL."
                            if state.fault == "journal-pid"
                            else "Killing process 113150 (python3) with signal SIGKILL."
                        ),
                    )
                ),
            )
        if argv[1] == "stop":
            if state.fault == "stop" or (
                state.fault == "final-stop" and argv[-1].endswith("-metadata.service")
            ):
                raise subprocess.CalledProcessError(1, argv)
        fields = "LoadState=loaded\nActiveState=failed\nControlGroup=\n"
        if state.fault == "cgroup":
            fields = fields.replace("ControlGroup=\n", "ControlGroup=/still-populated\n")
        return subprocess.CompletedProcess(argv, 0, stdout=fields)

    def adapter(request_id):
        state.adapter = systemd.SystemdAdapter(request_id, runner=run)
        return state.adapter

    monkeypatch.setattr(harness, "SystemdAdapter", adapter)
    monkeypatch.setattr(harness.subprocess, "run", run)

    def show(unit, *properties):
        fields = dict(
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
        if state.fault == "status":
            fields["Result"] = "exit-code"
        if state.fault == "helper":
            fields["ExecMainStatus"] = "1"
        if state.fault == "unit":
            fields["Id"] = "unrelated.service"
        if state.fault == "missing-status":
            fields["ExecMainCode"] = ""
        return {key: fields[key] for key in properties}

    monkeypatch.setattr(harness, "show", show)

    def sample(unit, candidate):
        state.sampled.set()
        samples = {
            113150: dict(
                uid=[997] * 4,
                gid=[988] * 4,
                nnp="1",
                caps=[0] * 5,
                mnt="mnt:[worker]",
                net="net:[worker]",
                observer_mnt="mnt:[observer]",
                observer_net="net:[observer]",
                interfaces=["lo"],
                ipv4_routes=[],
                ipv6_interfaces=["lo"],
                argv=["/usr/bin/python3", "-I", str(candidate / "installer/config_migrations.py")],
                sigign=1 << 14,
            )
        }
        if state.fault == "live-uid":
            samples[113150]["uid"] = [0] * 4
        if state.fault == "nnp":
            samples[113150]["nnp"] = "0"
        if state.fault == "caps":
            samples[113150]["caps"][3] = 1
        if state.fault in ("mnt", "net"):
            samples[113150][state.fault] = samples[113150]["observer_" + state.fault]
        if state.fault == "network":
            samples[113150]["interfaces"].append("eth0")
        if state.fault == "sigterm":
            samples[113150]["sigign"] = 0
        if state.fault == "missing-live":
            return {}
        if state.fault != "missing-helper":
            samples[113146] = copy.deepcopy(samples[113150])
            samples[113146]["argv"] = [
                "/usr/bin/python3",
                "-I",
                "/usr/local/libexec/knx_to_openhab/update_prepare.py",
            ]
        return samples

    # Also permits the same two regression cases to run against the historical
    # pre-fix callback for an offline RED comparison, without editing that blob.
    state.real_sample = getattr(harness, "_sample_hostile_processes", None)
    monkeypatch.setattr(harness, "_sample_hostile_processes", sample, raising=False)
    state.invoke = lambda: harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer(
        ({}, paths)
    )
    state.harness = harness
    state.mapped_path = mapped_path
    return state


def test_expected_manager_failure_reaches_confinement_evidence(replay, capsys):
    replay.invoke()
    assert replay.adapter.stopped == set(systemd.STAGES)
    operation = next(argv for argv in replay.calls if argv[0] == "/usr/bin/systemd-run")
    assert {
        "--property=TimeoutStopSec=15",
        "--property=KillMode=control-group",
        "--property=SendSIGKILL=yes",
    } <= set(operation)
    assert "expected operation failure; confinement/termination PASS" in capsys.readouterr().out


def test_effect_failure_still_attempts_every_owned_stage(replay):
    replay.fault = "effect"
    with pytest.raises(OSError, match="effect failed"):
        replay.invoke()
    stopped = [argv[-1] for argv in replay.calls if argv[:2] == ["/usr/bin/systemctl", "stop"]]
    assert {replay.adapter._unit(stage) for stage in systemd.STAGES} <= set(stopped)


@pytest.mark.parametrize(
    "fault",
    [
        "status",
        "helper",
        "stop",
        "final-stop",
        "cgroup",
        "heartbeat",
        "uid",
        "denied",
        "sudo",
        "unexpected-success",
        "unexpected-exit",
        "unrelated-error",
        "unit",
        "missing-status",
        "journal-unit",
        "journal-pid",
        "live-uid",
        "nnp",
        "caps",
        "mnt",
        "net",
        "network",
        "sigterm",
        "missing-live",
        "missing-helper",
        "alive",
        "cgroup-present",
    ],
)
def test_incomplete_or_unexpected_outcome_rejected_with_all_stage_cleanup(replay, fault, capsys):
    replay.fault = fault
    with pytest.raises(
        (
            AssertionError,
            ValueError,
            FileNotFoundError,
            subprocess.SubprocessError,
            pytest.fail.Exception,
        )
    ):
        replay.invoke()
    stopped = [argv[-1] for argv in replay.calls if argv[:2] == ["/usr/bin/systemctl", "stop"]]
    assert {replay.adapter._unit(stage) for stage in systemd.STAGES} <= set(stopped)
    assert "confinement/termination PASS" not in capsys.readouterr().out


def test_live_reader_uses_actual_proc_fields_not_unit_properties(replay, tmp_path, monkeypatch):
    unit = "knxohupdate-00000000-0000-4000-8000-000000000001-migrate.service"
    cgroup = "/system.slice/" + unit
    group = replay.mapped_path("/sys/fs/cgroup" + cgroup)
    group.mkdir(parents=True)
    (group / "cgroup.procs").write_text("113150\n113151\n")
    proc = replay.mapped_path("/proc") / "113150"
    (proc / "net").mkdir(parents=True)
    candidate = tmp_path / "candidate"
    (proc / "cmdline").write_bytes(
        (
            "/usr/bin/python3\0-I\0" + str(candidate / "installer/config_migrations.py") + "\0"
        ).encode()
    )
    (proc / "status").write_text(
        "Uid:\t997 997 997 997\nGid:\t988 988 988 988\nNoNewPrivs:\t1\n"
        "CapInh:\t0\nCapPrm:\t0\nCapEff:\t0\nCapBnd:\t0\nCapAmb:\t0\nSigIgn:\t4000\n"
    )
    (proc / "cgroup").write_text("0::" + cgroup + "\n")
    (proc / "net/dev").write_text("header\nheader\n lo: 0 0 0\n")
    (proc / "net/route").write_text("Iface Destination\n")
    (proc / "net/ipv6_route").write_text("00000000 lo\n")
    (proc / "net/if_inet6").write_text("00000001 lo\n")
    readlink = replay.harness.os.readlink

    def namespace(path, *args, **kwargs):
        if str(path).startswith("/proc/self/ns/"):
            return str(path).rsplit("/", 1)[-1] + ":[1]"
        if "113150" in str(path):
            return Path(path).name + ":[2]"
        return readlink(path, *args, **kwargs)

    monkeypatch.setattr(replay.harness.os, "readlink", namespace)
    samples = replay.real_sample(unit, candidate)
    assert set(samples) == {113150}  # second PID disappeared: not invented as evidence
    worker = SimpleNamespace(pw_uid=997, pw_gid=988)
    replay.harness._assert_hostile_process(samples[113150], worker)
    (proc / "status").write_text(
        (proc / "status").read_text().replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")
    )
    with pytest.raises(AssertionError):
        replay.harness._assert_hostile_process(replay.real_sample(unit, candidate)[113150], worker)


def test_changed_heartbeat_rejected_and_all_stages_stopped(replay, monkeypatch, capsys):
    read_bytes = Path.read_bytes
    reads = []

    def changed(path):
        value = read_bytes(path)
        if path.name == "heartbeat":
            reads.append(value)
            return value + str(len(reads)).encode()
        return value

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AssertionError):
        replay.invoke()
    assert len(reads) == 2
    assert replay.adapter.stopped == set(systemd.STAGES)
    assert "confinement/termination PASS" not in capsys.readouterr().out
