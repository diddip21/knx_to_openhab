"""Portable tests: no WSL invocation, manager access, or guest mutations."""

import copy
import json
from subprocess import CompletedProcess

import pytest

from scripts import nested_acceptance as guard


@pytest.fixture
def evidence():
    receipt = {
        "format": 1,
        "provider": "fresh-wsl2-nspawn",
        "distribution": "KNXOH-Acceptance-20261030",
        "install_location": "C:/Users/Username/AppData/Local/Temp/opencode/knxoh-wsl-acceptance-20261030",
        "outer_machine_id": "7b2bd160fe364cc89aebcbdc87a09a26",
        "inner_machine_id": "a50e862ca2e04dbda6720e0337e3d3da",
        "machine": "knxoh-acceptance",
        "nonce": "ab" * 32,
    }
    observed = {
        "machine_id": receipt["inner_machine_id"],
        "pid1": "systemd",
        "container": "systemd-nspawn",
        "pid1_container": "systemd-nspawn",
        "mounts": "1 0 0:1 / / rw - ext4 /dev/sdb rw\n",
        "interop": False,
    }
    return receipt, observed


def test_explicit_nested_identity_admitted(evidence):
    receipt, observed = evidence
    guard.validate_receipt(receipt)
    guard.validate_inner(receipt, observed)


@pytest.mark.parametrize(
    "field", ["format", "provider", "distribution", "install_location", "machine"]
)
def test_wrong_provider_or_unapproved_host_refused(evidence, field):
    receipt, _ = evidence
    receipt[field] = "Ubuntu"
    with pytest.raises(ValueError):
        guard.validate_receipt(receipt)


@pytest.mark.parametrize("field", ["outer_machine_id", "inner_machine_id", "nonce"])
@pytest.mark.parametrize("value", [None, "", "0" * 32, "AB" * 32, "placeholder"])
def test_malformed_identity_refused(evidence, field, value):
    receipt, _ = evidence
    receipt[field] = value
    with pytest.raises(ValueError):
        guard.validate_receipt(receipt)


def test_host_and_guest_cannot_share_identity(evidence):
    receipt, _ = evidence
    receipt["inner_machine_id"] = receipt["outer_machine_id"]
    with pytest.raises(ValueError):
        guard.validate_receipt(receipt)


def test_exact_receipt_schema(evidence):
    receipt, _ = evidence
    for field in receipt:
        broken = copy.deepcopy(receipt)
        del broken[field]
        with pytest.raises(ValueError):
            guard.validate_receipt(broken)
    receipt["allow_host"] = True
    with pytest.raises(ValueError):
        guard.validate_receipt(receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("machine_id", "7b2bd160fe364cc89aebcbdc87a09a26"),
        ("pid1", "init"),
        ("container", "wsl"),
        ("pid1_container", ""),
        ("interop", True),
        ("mounts", "1 0 0:1 / /mnt/c rw - 9p C: rw\n"),
        ("mounts", "1 0 0:1 / /mnt/c rw - drvfs C: rw\n"),
        ("mounts", ""),
    ],
)
def test_runtime_isolation_evidence_required(evidence, field, value):
    receipt, observed = evidence
    observed[field] = value
    with pytest.raises(ValueError):
        guard.validate_inner(receipt, observed)


def test_outer_binding_and_disabled_host_integration(evidence):
    receipt, _ = evidence
    observed = {
        "machine_id": receipt["outer_machine_id"],
        "mounts": "1 0 0:1 / / rw - ext4 /dev/sdb rw\n",
        "interop": False,
        "wsl_conf": "[automount]\nenabled=false\n[interop]\nenabled=false\nappendWindowsPath=false\n",
    }
    guard.validate_outer(receipt, observed)
    for field, value in [("machine_id", receipt["inner_machine_id"]), ("wsl_conf", "")]:
        broken = {**observed, field: value}
        with pytest.raises(ValueError):
            guard.validate_outer(receipt, broken)


def test_duplicate_receipt_keys_refused():
    with pytest.raises(ValueError):
        guard.decode_receipt('{"nonce":"a","nonce":"b"}')


@pytest.mark.parametrize(
    "records",
    [
        [],
        [{"DistributionName": "Ubuntu"}],
        [
            {"DistributionName": guard.DISTRIBUTION, "BasePath": "C:/wrong", "Version": 2},
        ],
        [
            {"DistributionName": guard.DISTRIBUTION, "BasePath": guard.LOCATION, "Version": 1},
        ],
    ],
)
def test_windows_registration_must_match_approved_import(records):
    with pytest.raises(ValueError):
        guard.validate_registration(records)


def test_windows_registration_matches_exact_path():
    guard.validate_registration(
        [
            {
                "DistributionName": guard.DISTRIBUTION,
                "BasePath": guard.LOCATION.replace("/", "\\"),
                "Version": 2,
            }
        ]
    )


def test_invalid_receipt_precedes_any_wsl_command(evidence):
    receipt, _ = evidence
    receipt["distribution"] = "Ubuntu"
    calls = []
    with pytest.raises(ValueError):
        guard.preflight(receipt, run=lambda *a, **k: calls.append(a))
    assert calls == []


def test_wrong_outer_prevents_contacting_nested_manager(evidence):
    receipt, _ = evidence
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(argv, 0, json.dumps({"machine_id": "cd" * 16}), "")

    with pytest.raises(ValueError, match="Wrong outer"):
        guard.preflight(receipt, run=run)
    assert calls == [["wsl.exe", "-d", guard.DISTRIBUTION, "--", "/usr/bin/python3", "-"]]


def test_preflight_uses_only_explicit_guest_and_stdin_observers(evidence):
    receipt, inner = evidence
    calls = []
    outer = {
        "machine_id": receipt["outer_machine_id"],
        "mounts": inner["mounts"],
        "interop": False,
        "wsl_conf": "[automount]\nenabled=false\n[interop]\nenabled=false\nappendWindowsPath=false\n",
    }

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, json.dumps(outer if len(calls) == 1 else inner), "")

    assert guard.preflight(receipt, run=run) == {"outer": outer, "inner": inner}
    assert len(calls) == 2
    for argv, kwargs in calls:
        assert argv[:4] == ["wsl.exe", "-d", guard.DISTRIBUTION, "--"]
        assert argv[-2:] == ["/usr/bin/python3", "-"]
        assert kwargs["check"] is True and kwargs["timeout"] == 60
        assert "mounts=text('/proc/self/mountinfo')" in kwargs["input"]
    assert calls[1][0][4:10] == [
        "/usr/bin/systemd-run",
        "--machine=" + guard.MACHINE,
        "--wait",
        "--pipe",
        "--collect",
        "/usr/bin/python3",
    ]
