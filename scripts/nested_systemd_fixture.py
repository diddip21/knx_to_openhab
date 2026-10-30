"""Own nested-guest acceptance phases, NEVER a production installer.

The Windows controller must run the reviewed registration/outer preflight before
each invocation. Each phase additionally authenticates the reviewed inner receipt
and live identity/mount evidence before any application effect. No cleanup of an
existing installation is implemented: partial fixtures/evidence are retained.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HARNESS = Path("/opt/knxoh-harness-d1f1848")
SOURCE = Path("/opt/knxoh-source-27d106a")
BASE = Path("/srv/knxoh acceptance app")
CONFIG = Path("/etc/knxoh acceptance config")
DATA = Path("/var/lib/knxoh acceptance data")
BACKUPS = Path("/var/backups/knxoh acceptance backups")
OUTPUT = Path("/srv/knxoh acceptance generated")
PATHS_FILE = CONFIG / "paths.env"


def require_guest(nonce):
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Fixture requires the authorized nested root controller")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(HARNESS))
    sys.path.insert(0, str(HARNESS / "tests/integration"))
    harness = importlib.import_module("test_update_systemd")
    harness._check_virtualization("systemd-nspawn", nonce)
    # The receipt schema pins the provider; also pin this fixture's actual IDs.
    if Path("/etc/machine-id").read_text().strip() != "a50e862ca2e04dbda6720e0337e3d3da":
        raise ValueError("Wrong application fixture machine")
    return harness


def command(argv, *, timeout=180, **kwargs):
    print("RUN", argv[0], *argv[1:3], flush=True)
    return subprocess.run(argv, check=True, timeout=timeout, **kwargs)


def write_new(path, raw, mode=0o600, gid=0):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchown(stream.fileno(), 0, gid)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def bootstrap(nonce):
    import pwd

    harness = require_guest(nonce)
    for path in (BASE, CONFIG, DATA, BACKUPS, OUTPUT):
        if path.exists() or path.is_symlink():
            raise ValueError("Fresh fixture destination already exists: " + str(path))
    for name in ("knxohui", "knxohupdate"):
        try:
            pwd.getpwnam(name)
        except KeyError:
            pass
        else:
            raise ValueError("Fresh fixture account already exists: " + name)
    source_receipt = json.loads(SOURCE.with_suffix(".receipt.json").read_text())
    assert source_receipt["head"] == "27d106a26c907b7ce05d1880ea25157b1f815e50"
    assert source_receipt["all_file_hashes_verified"] is True
    # Only this inner guest's local hostname. Avoid ambiguous sudo-policy queries.
    hostname = socket.gethostname()
    hosts = Path("/etc/hosts")
    if hostname not in hosts.read_text().split():
        with hosts.open("a") as stream:
            stream.write("\n127.0.1.1 " + hostname + "\n")
    command(["/usr/sbin/groupadd", "--system", "knxohui"])
    command(
        [
            "/usr/sbin/useradd",
            "--system",
            "--gid",
            "knxohui",
            "--no-create-home",
            "--home-dir",
            "/nonexistent",
            "--shell",
            "/usr/sbin/nologin",
            "knxohui",
        ]
    )
    ui = pwd.getpwnam("knxohui")
    for path in (BASE, BASE / "releases", CONFIG, DATA, BACKUPS, OUTPUT):
        path.mkdir(mode=0o755 if path in (BASE, BASE / "releases", OUTPUT) else 0o750)
    os.chown(CONFIG, 0, ui.pw_gid)
    for path in (DATA, BACKUPS):
        os.chown(path, ui.pw_uid, ui.pw_gid)
    for name in ("jobs", "staging", "generated"):
        path = DATA / name
        path.mkdir(mode=0o750)
        os.chown(path, ui.pw_uid, ui.pw_gid)
    config = {
        "schema_version": 0,
        "bind_host": "127.0.0.1",
        "port": 8085,
        "openhab_path": str(OUTPUT),
        "auth": {"enabled": True, "user": "acceptance"},
        "general": {"auto_place_unknown": False},
        "acceptance_sibling": {"keep": [1, 2]},
    }
    write_new(CONFIG / "config.json", json.dumps(config).encode(), 0o640, ui.pw_gid)
    write_new(CONFIG / "generator.json", (SOURCE / "config.json").read_bytes(), 0o640, ui.pw_gid)
    raw_paths = "".join(
        f'{key}="{path}"\n'
        for key, path in (
            ("KNXOH_INSTALL_DIR", BASE),
            ("KNXOH_CONFIG_DIR", CONFIG),
            ("KNXOH_DATA_DIR", DATA),
            ("KNXOH_BACKUP_DIR", BACKUPS),
        )
    )
    write_new(PATHS_FILE, raw_paths.encode(), 0o644)
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths

    paths = Paths(BASE / "releases", BASE / "current", CONFIG, DATA, BACKUPS)
    require_guest(nonce)
    with admin.installer_lease(paths, PATHS_FILE):
        worker = admin.provision_worker()
        admin.provision_state(paths, worker)
        admin.install_components(SOURCE / "installer", paths, PATHS_FILE)
    harness._check_worker_policy()
    print("REAL administrator-installed bundle and worker policy PASS", flush=True)
    release = paths.releases / "0.1.0"
    shutil.copytree(SOURCE, release, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    require_guest(nonce)
    # This is a new administrator-created environment from the verified source
    # and approved offline wheels, not a worker/candidate-created environment.
    command(["/usr/bin/python3", "-I", "-m", "venv", "--copies", str(release / "venv")])
    python = str(release / "venv/bin/python")
    command(
        [
            python,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--find-links",
            "/opt/knxoh-wheelhouse",
            "--only-binary=:all:",
            "--no-compile",
            "-r",
            str(release / "requirements.txt"),
        ],
        timeout=300,
    )
    alias = release / "venv/lib64"
    if alias.is_symlink() and os.readlink(alias) == "lib":
        alias.unlink()
    password = secrets.token_hex(24)
    hashed = command(
        [
            python,
            "-I",
            "-c",
            "from argon2 import PasswordHasher; print(PasswordHasher().hash(input()))",
        ],
        input=password + "\n",
        text=True,
        capture_output=True,
    ).stdout.strip()
    secret = (
        "KNXOH_UI_PASSWORD_HASH_B64="
        + base64.b64encode(hashed.encode()).decode()
        + "\nKNXOH_SESSION_SECRET_B64="
        + base64.b64encode(secrets.token_bytes(48)).decode()
        + "\n"
    )
    write_new(CONFIG / "secrets.env", secret.encode(), 0o640, ui.pw_gid)
    write_new(
        Path("/root/knxoh-acceptance-login.json"),
        json.dumps({"user": "acceptance", "password": password}).encode(),
    )
    os.symlink(str(release), paths.current)
    for name in (
        "items/knx.items",
        "things/knx.things",
        "sitemaps/knx.sitemap",
        "persistence/influxdb.persist",
        "rules/fenster.rules",
    ):
        path = OUTPUT / name
        path.parent.mkdir(mode=0o755, exist_ok=True)
        write_new(path, b"", 0o644)
        os.chown(path, ui.pw_uid, ui.pw_gid)
    require_guest(nonce)
    command(["/usr/bin/systemctl", "daemon-reload"])
    command(
        [
            "/usr/bin/systemctl",
            "enable",
            "knxohui-update-recovery.service",
            "knxohui.service",
            "knxohui-backup-cleanup.timer",
        ]
    )
    command(["/usr/bin/systemctl", "start", "knxohui-update-recovery.service"], timeout=90)
    command(["/usr/bin/systemctl", "start", "knxohui.service"], timeout=90)
    command(["/usr/bin/systemctl", "start", "knxohui-backup-cleanup.service"], timeout=90)
    print("REAL initial installed units started", flush=True)


def probe(nonce):
    harness = require_guest(nonce)
    from installer.update_core.transaction import load_paths

    harness._check_worker_policy()
    paths = load_paths(PATHS_FILE)
    harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer(({}, paths))
    print("REAL installed hostile migration/cgroup teardown PASS", flush=True)


def run_phase(phase, nonce):
    handlers = {"bootstrap": bootstrap, "probe": probe}
    if phase not in handlers:
        raise ValueError("Unsupported nested fixture phase")
    require_guest(nonce)
    return handlers[phase](nonce)
