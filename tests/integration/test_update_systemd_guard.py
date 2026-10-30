"""Portable fake/read-only harness gating tests; NEVER contact a live manager."""

import copy
import json
import stat
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest
import test_update_systemd as harness

from installer.update_core.transaction import load_paths as REAL_LOAD_PATHS

NONCE = "a1" * 32
BOOT = "12345678-1234-4234-8234-123456789abc"
PRIOR = "87654321-4321-4321-8321-cba987654321"
MACHINE = "ab" * 16
MISSING = object()
CHECK_WORKER_POLICY = harness._check_worker_policy


@pytest.fixture
def fake_guest(monkeypatch):
    # Bootstrap binds load_paths at import time. Import it BEFORE patching the
    # transaction reader, or its alias would retain a fixture lambda after undo.
    from installer import update_bootstrap

    marker = {"disposable": True, "machine_id": MACHINE, "nonce": NONCE}
    config = {
        "nonce": NONCE,
        "paths_file": "/etc/knxoh/paths.env",
        "prior_boot_id": PRIOR,
        "offline_lock_absent": True,
    }
    env = {
        "KNXOH_DISPOSABLE_SYSTEMD_CONFIG": "/root/acceptance.json",
        "KNXOH_DISPOSABLE_SYSTEMD": "destroy-this-guest",
        "KNXOH_DISPOSABLE_SYSTEMD_NONCE": NONCE,
    }
    guest = SimpleNamespace(
        marker=marker,
        config=config,
        env=env,
        boot=BOOT,
        machine=MACHINE,
        virt="kvm",
        pid1="systemd",
        calls=[],
        mutations=[],
        policy=[],
        modes={},
        owners={},
        raw={},
        missing=set(),
        bootstrap=update_bootstrap,
    )

    class FakePath:
        def __init__(self, path):
            self.path = str(path)

        def __str__(self):
            return self.path

        def exists(self):
            return self.path in guest.raw and self.path not in guest.missing

        def lstat(self):
            return SimpleNamespace(
                st_uid=guest.owners.get(self.path, 0),
                st_mode=stat.S_IFREG | guest.modes.get(self.path, 0o600),
            )

        def read_text(self):
            if self.path in guest.missing:
                raise FileNotFoundError(self.path)
            if self.path in guest.raw:
                return guest.raw[self.path]
            return {
                "/etc/knxoh-disposable-systemd-test.json": json.dumps(guest.marker),
                "/root/acceptance.json": json.dumps(guest.config),
                "/etc/machine-id": guest.machine + "\n",
                "/proc/sys/kernel/random/boot_id": guest.boot + "\n",
                "/proc/1/comm": guest.pid1 + "\n",
            }[self.path]

    def run(argv, **kwargs):
        guest.calls.append(argv)
        if argv == ["systemd-detect-virt"]:
            return CompletedProcess(argv, 0, guest.virt + "\n", "")
        # A fake effect after the guard represents the first real test operation.
        # No systemctl or other command is ever executed by this spy.
        guest.mutations.append(argv)
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(harness, "Path", FakePath)
    monkeypatch.setattr(harness.os, "environ", env)
    monkeypatch.setattr(harness, "_root_process", lambda: True, raising=False)
    monkeypatch.setattr(
        harness, "_check_worker_policy", lambda: guest.policy.append("checked"), raising=False
    )
    monkeypatch.setattr(harness.subprocess, "run", run)
    from installer.update_core import transaction

    monkeypatch.setattr(
        transaction,
        "load_paths",
        lambda _path: SimpleNamespace(
            releases="/srv/custom app/releases",
            config_dir="/etc/custom config",
            data_dir="/var/lib/custom data",
            backup_dir="/var/lib/custom backups",
        ),
    )
    return guest


def assert_refused_without_effect(guest):
    refused = False
    try:
        harness.disposable.__wrapped__()
    except (AssertionError, ValueError, KeyError, TypeError, OSError):
        refused = True
    else:
        harness.subprocess.run(["/usr/bin/systemctl", "start", "knxohui.service"])
    assert guest.mutations == [], "malformed guard admitted a manager mutation"
    assert refused, "malformed guard admitted the disposable harness"
    assert guest.policy == []


@pytest.mark.parametrize("value", [MISSING, None, "", " ", "short", "A1" * 32, "gg" * 32, 7])
@pytest.mark.parametrize("location", ["env", "marker", "config", "all"])
def test_invalid_nonce_never_admits_manager_mutation(fake_guest, location, value):
    guest = fake_guest
    for selected in (["env", "marker", "config"] if location == "all" else [location]):
        data, key = (
            (guest.env, "KNXOH_DISPOSABLE_SYSTEMD_NONCE")
            if selected == "env"
            else (getattr(guest, selected), "nonce")
        )
        if value is MISSING:
            data.pop(key)
        else:
            data[key] = value
    assert_refused_without_effect(guest)
    assert guest.calls == []  # strict attestations precede even read-only subprocesses


@pytest.mark.parametrize(
    "value",
    [
        MISSING,
        None,
        "",
        " ",
        "placeholder",
        7,
        "00000000-0000-0000-0000-000000000000",
        BOOT,
        PRIOR.upper(),
        PRIOR.replace("-", ""),
    ],
)
def test_invalid_or_unchanged_prior_boot_never_admits_manager_mutation(fake_guest, value):
    if value is MISSING:
        fake_guest.config.pop("prior_boot_id")
    else:
        fake_guest.config["prior_boot_id"] = value
    assert_refused_without_effect(fake_guest)
    assert fake_guest.calls == []


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "placeholder",
        "00000000-0000-0000-0000-000000000000",
        BOOT.upper(),
        BOOT.replace("-", ""),
    ],
)
def test_invalid_current_boot_never_admits_manager_mutation(fake_guest, value):
    fake_guest.boot = value if value is not None else "null"
    assert_refused_without_effect(fake_guest)
    assert fake_guest.calls == []


def test_missing_current_boot_file_never_admits_manager_mutation(fake_guest):
    fake_guest.missing.add("/proc/sys/kernel/random/boot_id")
    assert_refused_without_effect(fake_guest)
    assert fake_guest.calls == []


@pytest.mark.parametrize("location", ["env", "marker", "config"])
def test_well_formed_but_mismatched_nonce_refused(fake_guest, location):
    if location == "env":
        fake_guest.env["KNXOH_DISPOSABLE_SYSTEMD_NONCE"] = "b2" * 32
    else:
        getattr(fake_guest, location)["nonce"] = "b2" * 32
    assert_refused_without_effect(fake_guest)
    assert fake_guest.calls == []


@pytest.mark.parametrize(
    "target,edit",
    [
        ("marker", {"extra": True}),
        ("config", {"extra": True}),
        ("marker", {"disposable": 1}),
        ("config", {"offline_lock_absent": 1}),
        ("config", {"offline_lock_absent": False}),
        ("config", {"paths_file": ""}),
        ("config", {"paths_file": "relative.env"}),
        ("config", {"paths_file": None}),
        ("marker", {"machine_id": ""}),
        ("marker", {"machine_id": None}),
    ],
)
def test_strict_attestation_schemas_before_effects(fake_guest, target, edit):
    getattr(fake_guest, target).update(edit)
    assert_refused_without_effect(fake_guest)
    assert fake_guest.calls == []


@pytest.mark.parametrize("target", ["marker", "config"])
@pytest.mark.parametrize("value", [[], None, True, "placeholder"])
def test_nonobject_attestations_rejected(fake_guest, target, value):
    setattr(fake_guest, target, value)
    assert_refused_without_effect(fake_guest)


@pytest.mark.parametrize("target", ["marker", "config"])
def test_duplicate_attestation_fields_rejected(fake_guest, target):
    path = (
        "/etc/knxoh-disposable-systemd-test.json" if target == "marker" else "/root/acceptance.json"
    )
    original = json.dumps(getattr(fake_guest, target))
    fake_guest.raw[path] = original[:-1] + ',"nonce":' + json.dumps(NONCE) + "}"
    assert_refused_without_effect(fake_guest)


@pytest.mark.parametrize("target", ["marker", "config"])
def test_missing_schema_fields_rejected(fake_guest, target):
    for key in list(getattr(fake_guest, target)):
        original = copy.deepcopy(getattr(fake_guest, target))
        getattr(fake_guest, target).pop(key)
        assert_refused_without_effect(fake_guest)
        setattr(fake_guest, target, original)


def test_valid_attestations_allow_only_read_only_preflight(fake_guest):
    settings, paths = harness.disposable.__wrapped__()
    assert settings == fake_guest.config and " " in str(paths.releases)
    assert fake_guest.calls == [["systemd-detect-virt"]]
    assert fake_guest.policy == ["checked"]
    assert fake_guest.mutations == []


def test_guard_path_stub_does_not_escape_into_bootstrap_import(fake_guest):
    from installer import update_bootstrap

    assert update_bootstrap.load_paths is REAL_LOAD_PATHS


@pytest.mark.parametrize(
    "gate",
    [
        "opt-in",
        "root",
        "marker-owner",
        "marker-mode",
        "config-owner",
        "config-mode",
        "machine",
        "wsl",
        "host",
        "pid1",
    ],
)
def test_existing_disposable_gates_remain_required(fake_guest, monkeypatch, gate):
    if gate == "opt-in":
        fake_guest.env.pop("KNXOH_DISPOSABLE_SYSTEMD")
    elif gate == "root":
        monkeypatch.setattr(harness, "_root_process", lambda: False, raising=False)
    elif gate.endswith("owner") or gate.endswith("mode"):
        path = (
            "/etc/knxoh-disposable-systemd-test.json"
            if gate.startswith("marker")
            else "/root/acceptance.json"
        )
        getattr(fake_guest, "owners" if gate.endswith("owner") else "modes")[path] = (
            1000 if gate.endswith("owner") else 0o666
        )
    elif gate == "machine":
        fake_guest.machine = "cd" * 16
    elif gate in ("wsl", "host"):
        fake_guest.virt = "wsl" if gate == "wsl" else "none"
    else:
        fake_guest.pid1 = "not-systemd"
    assert_refused_without_effect(fake_guest)


@pytest.fixture
def fake_worker(fake_guest, monkeypatch):
    bootstrap = fake_guest.bootstrap

    worker = SimpleNamespace(
        pw_name="knxohupdate", pw_uid=501, pw_gid=501, pw_shell="/usr/sbin/nologin"
    )
    ui = SimpleNamespace(pw_name="knxohui", pw_uid=502, pw_gid=502)
    accounts = {"knxohupdate": worker, "knxohui": ui, "openhab": SimpleNamespace(pw_uid=503)}
    group_ids = {"knxohupdate": 501, "knxohui": 502, "openhab": 503, "sudo": 27, "wheel": 28}
    state = SimpleNamespace(
        worker=worker,
        ui=ui,
        memberships=[501],
        group_reads=[],
        sudo=[],
        allowed=False,
        ambiguous=False,
        alias=False,
    )

    def memberships(name, gid):
        state.group_reads.append((name, gid))
        return state.memberships

    def group(gid):
        name = next(name for name, value in group_ids.items() if value == gid)
        return SimpleNamespace(gr_name="innocent-alias" if state.alias else name)

    def run(argv, **kwargs):
        if argv == ["systemd-detect-virt"]:
            fake_guest.calls.append(argv)
            return CompletedProcess(argv, 0, fake_guest.virt + "\n", "")
        assert argv == ["/usr/bin/sudo", "-n", "-l", "-U", "knxohupdate"]
        assert kwargs["cwd"] == "/" and kwargs["env"]["LC_ALL"] == "C"
        assert kwargs["check"] is False and kwargs["timeout"] == 15
        state.sudo.append(argv)
        if state.allowed:
            return CompletedProcess(
                argv, 0, "User knxohupdate may run systemctl start knxohui.service\n", ""
            )
        if state.ambiguous:
            return CompletedProcess(argv, 1, "", "sudo: policy query failed\n")
        return CompletedProcess(
            argv, 1, "", "User knxohupdate is not allowed to run sudo on guest.\n"
        )

    monkeypatch.setattr(bootstrap, "pwd", SimpleNamespace(getpwnam=lambda name: accounts[name]))
    monkeypatch.setattr(
        bootstrap,
        "grp",
        SimpleNamespace(
            getgrgid=group, getgrnam=lambda name: SimpleNamespace(gr_gid=group_ids[name])
        ),
    )
    monkeypatch.setattr(bootstrap.os, "getgrouplist", memberships, raising=False)
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    monkeypatch.setattr(harness, "_check_worker_policy", CHECK_WORKER_POLICY)
    return state


@pytest.mark.parametrize(
    "unsafe",
    [
        "root-uid",
        "root-gid",
        "ui-uid",
        "ui-gid",
        "openhab-uid",
        "shell",
        "ui-group",
        "openhab-group",
        "sudo-group",
        "wheel-group",
        "gid-alias",
        "sudo-grant",
        "sudo-error",
    ],
)
def test_trusted_worker_preflight_refuses_identity_or_policy_before_effects(
    fake_guest, fake_worker, unsafe
):
    state = fake_worker
    if unsafe in ("root-uid", "root-gid", "ui-uid", "ui-gid", "openhab-uid"):
        field = "pw_gid" if unsafe.endswith("gid") else "pw_uid"
        setattr(
            state.worker,
            field,
            0 if unsafe.startswith("root") else 503 if unsafe.startswith("openhab") else 502,
        )
    elif unsafe == "shell":
        state.worker.pw_shell = "/bin/bash"
    elif unsafe.endswith("group") or unsafe == "gid-alias":
        state.memberships = [
            501,
            {
                "ui-group": 502,
                "openhab-group": 503,
                "sudo-group": 27,
                "wheel-group": 28,
                "gid-alias": 27,
            }[unsafe],
        ]
        state.alias = unsafe == "gid-alias"
    else:
        state.allowed = unsafe == "sudo-grant"
        state.ambiguous = unsafe == "sudo-error"
    assert_refused_without_effect(fake_guest)
    assert state.group_reads == [("knxohupdate", state.worker.pw_gid)]
    assert len(state.sudo) == (1 if unsafe in ("sudo-grant", "sudo-error") else 0)


def test_worker_preflight_queries_actual_memberships_and_sudo_listing_only(fake_guest, fake_worker):
    settings, _paths = harness.disposable.__wrapped__()
    assert settings == fake_guest.config
    assert fake_worker.group_reads == [("knxohupdate", 501)]
    assert fake_worker.sudo == [["/usr/bin/sudo", "-n", "-l", "-U", "knxohupdate"]]
    assert fake_guest.mutations == []  # never execute any worker sudo-granted action


@pytest.fixture
def nested_guest(fake_guest):
    from scripts.nested_acceptance import DISTRIBUTION, LOCATION
    from scripts.nested_acceptance import MACHINE as NESTED_MACHINE

    guest = fake_guest
    guest.virt = "wsl"
    guest.raw["/etc/knxoh-nested-acceptance.json"] = json.dumps(
        {
            "format": 1,
            "provider": "fresh-wsl2-nspawn",
            "distribution": DISTRIBUTION,
            "install_location": LOCATION,
            "outer_machine_id": "cd" * 16,
            "inner_machine_id": guest.machine,
            "machine": NESTED_MACHINE,
            "nonce": NONCE,
        }
    )
    guest.raw.update(
        {
            "/run/systemd/container": "systemd-nspawn\n",
            "/proc/1/environ": "container=systemd-nspawn\0",
            "/proc/self/mountinfo": "1 0 0:1 / / rw - ext4 /dev/sdb rw\n",
        }
    )
    return guest


def test_nested_provider_allows_attested_nspawn_not_blanket_wsl(nested_guest):
    settings, _paths = harness.disposable.__wrapped__()
    assert settings == nested_guest.config
    assert nested_guest.policy == ["checked"]
    assert nested_guest.mutations == []


@pytest.mark.parametrize(
    "gate", ["owner", "mode", "nonce", "outer", "container", "mount", "driver"]
)
def test_nested_provider_refuses_before_worker_or_service_effects(nested_guest, gate):
    guest = nested_guest
    path = "/etc/knxoh-nested-acceptance.json"
    if gate in ("owner", "mode"):
        getattr(guest, "owners" if gate == "owner" else "modes")[path] = (
            1000 if gate == "owner" else 0o644
        )
    elif gate in ("nonce", "outer"):
        receipt = json.loads(guest.raw[path])
        receipt["nonce" if gate == "nonce" else "inner_machine_id"] = "b2" * (
            32 if gate == "nonce" else 16
        )
        guest.raw[path] = json.dumps(receipt)
    elif gate == "container":
        guest.raw["/run/systemd/container"] = "wsl"
    elif gate == "driver":
        guest.raw["/proc/self/mountinfo"] = (
            "172 175 0:36 / /usr/lib/wsl/drivers ro,nosuid,nodev - 9p drivers ro\n"
        )
    else:
        guest.raw["/proc/self/mountinfo"] = "1 0 0:1 / /mnt/c rw - 9p C: rw\n"
    assert_refused_without_effect(guest)
