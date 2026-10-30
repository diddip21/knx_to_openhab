"""Opt-in, read-only installed-unit regression for custom paths with spaces.

Run only in the approved own nested fixture after controller preflight. Queries
real PID-1 D-Bus state. The separate parser opt-in writes only uniquely named
disposable fixture units; neither mode starts services or patches app units.
"""

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


def _bus(*arguments):
    result = subprocess.run(
        ["/usr/bin/busctl", "--system", "--json=short", *arguments],
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(result.stdout)


def _file_entries(value):
    if not isinstance(value, list):
        return []
    if len(value) == 2 and isinstance(value[0], str) and type(value[1]) is bool:
        return [(value[0], value[1])]
    return [entry for child in value for entry in _file_entries(child)]


@pytest.mark.parametrize(
    "data,expected",
    [
        ([], []),
        (
            ["/etc/config with spaces/paths.env", False],
            [("/etc/config with spaces/paths.env", False)],
        ),
        (
            [["/etc/config with spaces/paths.env", False]],
            [("/etc/config with spaces/paths.env", False)],
        ),
        (
            [[["/etc/config with spaces/paths.env", False]]],
            [("/etc/config with spaces/paths.env", False)],
        ),
    ],
)
def test_environment_property_decoder(data, expected):
    assert _file_entries(data) == expected


@pytest.mark.parametrize("unit", ["knxohui.service", "knxohui-backup-cleanup.service"])
def test_installed_writer_loads_actual_custom_paths_environment(unit):
    if os.environ.get("KNXOH_LIVE_SYSTEMD_ENV_ACCEPTANCE") != "own-nested-read-only":
        pytest.skip("opt-in own-nested installed EnvironmentFile regression not configured")
    import test_update_systemd as harness

    from installer import update_bootstrap as admin
    from installer.update_core import secure_fs as fs
    from installer.update_core.transaction import load_paths

    assert harness._root_process()
    harness._check_virtualization(
        "systemd-nspawn", os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_NONCE")
    )
    config = Path("/etc/knxoh acceptance config")
    base = Path("/srv/knxoh acceptance app")
    contract = config / "paths.env"
    paths = admin.Paths(
        base / "releases",
        base / "current",
        config,
        Path("/var/lib/knxoh acceptance data"),
        Path("/var/backups/knxoh acceptance backups"),
    )
    assert load_paths(contract) == paths
    dropin = Path("/etc/systemd/system") / (unit + ".d") / "50-knxohui-paths.conf"
    assert (
        fs.read_regular(dropin, 4096) == admin.render_dropins(paths, contract)[unit].encode()
    ), "test must inspect the actual production-rendered drop-in, not a fixture replacement"
    obj = _bus(
        "call",
        "org.freedesktop.systemd1",
        "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager",
        "GetUnit",
        "s",
        unit,
    )
    assert obj["type"] == "o" and len(obj["data"]) == 1
    environment = _bus(
        "get-property",
        "org.freedesktop.systemd1",
        obj["data"][0],
        "org.freedesktop.systemd1.Service",
        "EnvironmentFiles",
    )
    assert environment["type"] == "a(sb)"
    actual = _file_entries(environment["data"])
    assert actual == [(str(contract), False)], (
        f"actual PID-1 {unit} EnvironmentFiles={actual!r}; "
        "protected custom paths contract was not loaded"
    )


@pytest.mark.parametrize("writer", ["knxohui.service", "knxohui-backup-cleanup.service"])
def test_disposable_pid1_parses_production_environment_file(writer):
    if os.environ.get("KNXOH_LIVE_SYSTEMD_ENV_ACCEPTANCE") != "own-nested-parser":
        pytest.skip("opt-in own-nested disposable PID-1 parser regression not configured")
    import test_update_systemd as harness

    from installer import update_bootstrap as admin

    assert harness._root_process()
    # This opt-in is specifically for the authenticated own nested fixture, not
    # arbitrary virtualized hosts. The shared check authenticates this receipt.
    assert Path("/etc/knxoh-nested-acceptance.json").exists()
    virt = subprocess.run(
        ["/usr/bin/systemd-detect-virt"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    harness._check_virtualization(
        virt.stdout.strip(), os.environ.get("KNXOH_DISPOSABLE_SYSTEMD_NONCE")
    )
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    contract = Path("/etc/knxoh acceptance config/paths.env")
    base = Path("/srv/knxoh acceptance app")
    paths = admin.Paths(
        base / "releases",
        base / "current",
        contract.parent,
        Path("/var/lib/knxoh acceptance data"),
        Path("/var/backups/knxoh acceptance backups"),
    )
    name = f"knxoh-env-parser-{uuid4().hex}.service"
    fixture = Path("/run/systemd/system") / name
    # No app unit edits, daemon-reload, starts, environment injection or contract
    # reads. LoadUnit parses this new unique fragment directly. The inherited
    # entry proves the production reset leaves exactly one REQUIRED file.
    text = (
        "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
        "EnvironmentFile=/nonexistent-inherited.env\n"
        + admin.render_dropins(paths, contract)[writer]
    )
    stream = fixture.open("x")
    try:
        with stream:
            stream.write(text)
        obj = _bus(
            "call",
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager",
            "LoadUnit",
            "s",
            name,
        )
        assert obj["type"] == "o" and len(obj["data"]) == 1
        environment = _bus(
            "get-property",
            "org.freedesktop.systemd1",
            obj["data"][0],
            "org.freedesktop.systemd1.Service",
            "EnvironmentFiles",
        )
        assert environment["type"] == "a(sb)"
        assert _file_entries(environment["data"]) == [(str(contract), False)]
    finally:
        fixture.unlink()  # only this exclusively created fixture, never app files
