"""Own nested-guest acceptance phases, NEVER a production installer.

The Windows controller must run the reviewed registration/outer preflight before
each invocation. Each phase additionally authenticates the reviewed inner receipt
and live identity/mount evidence before any application effect. No cleanup of an
existing installation is implemented: partial fixtures/evidence are retained.
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from scripts.nested_fixture_state import (
    LOCK,
    collect_inventory,
    validate_checkpoint,
    validate_fresh,
    verify_source_approval,
)

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
    harness = require_guest(nonce)
    validate_fresh(collect_inventory())
    from installer import update_bootstrap as admin

    with admin.installer_lease(expected_paths(), PATHS_FILE) as fd:
        validate_fresh(collect_inventory())
        _seed_fresh(nonce, harness, inherited=fd)
    _activate(nonce)


def _seed_fresh(nonce, harness, inherited=None):
    import pwd

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
    with admin.installer_lease(paths, PATHS_FILE, inherited=inherited):
        worker = admin.provision_worker()
        admin.provision_state(paths, worker)
        admin.install_components(SOURCE / "installer", paths, PATHS_FILE)
    harness._check_worker_policy()
    print("REAL administrator-installed bundle and worker policy PASS", flush=True)
    _prepare_initial(nonce, paths, SOURCE)


def _prepare_initial(nonce, paths, source):
    import pwd

    require_guest(nonce)
    ui = pwd.getpwnam("knxohui")
    release = paths.releases / "0.1.0"
    shutil.copytree(source, release, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
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


def _activate(nonce):
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


def probe(nonce, source_approval=None, approved_head=None):
    harness = require_guest(nonce)
    from installer.update_core.transaction import load_paths

    paths = load_paths(PATHS_FILE)
    if paths != expected_paths():
        raise ValueError("Off-fixture paths contract")
    validate_probe_roots(paths)
    validate_preparation()
    if source_approval is None and approved_head is None:
        harness._check_worker_policy()
    else:
        admin = load_approved_admin(verify_source_approval(source_approval, approved_head))
        admin.check_worker()
        admin.check_worker_sudo()
    harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer(({}, paths))
    print("REAL installed hostile migration/cgroup teardown PASS", flush=True)


def expected_paths():
    from installer.update_core.protocol import Paths

    return Paths(BASE / "releases", BASE / "current", CONFIG, DATA, BACKUPS)


def validate_probe_roots(paths):
    import pwd
    import stat

    from installer.update_core import secure_fs as fs
    from installer.update_core.state import _current_target

    ui = pwd.getpwnam("knxohui")
    roots = (
        (BASE, 0, 0, 0o755),
        (paths.releases, 0, 0, 0o755),
        (CONFIG, 0, ui.pw_gid, 0o750),
        (DATA, ui.pw_uid, ui.pw_gid, 0o750),
        (BACKUPS, ui.pw_uid, ui.pw_gid, 0o750),
        (Path("/usr/local/libexec/knx_to_openhab"), 0, 0, 0o755),
    )
    for path, uid, gid, mode in roots:
        with fs._parent(path) as (stack, parent, name, chain):
            pinned = fs._open(stack, parent, name, {uid}, os.fstat(parent).st_dev, directory=True)
            if pinned.info.st_gid != gid or stat.S_IMODE(pinned.info.st_mode) != mode:
                raise ValueError("Unsafe installed fixture path")
            fs._check([*chain, pinned])
    _current_target(paths)
    fs.read_regular(Path("/usr/local/libexec/knx_to_openhab/update_prepare.py"), 1024 * 1024)


def validate_preparation(*, fs=None, worker_gid=None):
    if fs is None:
        from installer.update_core import secure_fs as fs
    from scripts.nested_fixture_state import PREPARATION

    if worker_gid is None:
        import pwd

        worker_gid = pwd.getpwnam("knxohupdate").pw_gid
    with fs._parent(PREPARATION) as (stack, parent, name, chain):
        entry = fs._open(stack, parent, name, {0}, fs.os.fstat(parent).st_dev, directory=True)
        import stat

        if (
            entry.info.st_uid != 0
            or not stat.S_ISDIR(entry.info.st_mode)
            or entry.info.st_gid != worker_gid
            or stat.S_IMODE(entry.info.st_mode) != 0o750
        ):
            raise ValueError("Unsafe fixed preparation parent")
        fs._check([*chain, entry])


def load_approved_admin(source):
    spec = importlib.util.spec_from_file_location(
        "_knxoh_acceptance_reviewed_admin", source / "installer/update_bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def admin_paths(admin):
    # The standalone verified bootstrap loads its own protocol package. Use its
    # class as well as its code; cross-package dataclass equality is not equal.
    return admin.Paths(BASE / "releases", BASE / "current", CONFIG, DATA, BACKUPS)


@contextmanager
def resume_lease(admin, checkpoint):
    import fcntl

    from installer.update_core import secure_fs as fs
    from installer.update_core.state import LifecycleLock

    expected = checkpoint["inventory"]["entries"][LOCK.as_posix()]
    # Open the existing inode ONLY: no O_CREAT, unlink, or replacement on refusal.
    with LifecycleLock()._parent() as (stack, parent, name, chain):
        entry = fs._open(stack, parent, name, {0}, None)
        info = entry.info
        if (
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_gid,
            info.st_mode & 0o7777,
            info.st_nlink,
        ) != (expected["device"], expected["inode"], 0, 0, 0o600, 1):
            raise ValueError("Pinned retained lock inode changed")
        fcntl.flock(entry.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fs._check([*chain, entry])
            with admin.installer_lease(admin_paths(admin), PATHS_FILE, inherited=entry.fd):
                yield
        finally:
            fcntl.flock(entry.fd, fcntl.LOCK_UN)


def resume_after_sudo(nonce, checkpoint, source_approval, approved_head):
    require_guest(nonce)
    validate_checkpoint(checkpoint, collect_inventory(details=True), nonce)
    source = verify_source_approval(source_approval, approved_head)
    admin = load_approved_admin(source)
    with resume_lease(admin, checkpoint):
        require_guest(nonce)
        validate_checkpoint(checkpoint, collect_inventory(details=True), nonce)
        verify_source_approval(source_approval, approved_head)
        worker = admin.check_worker()
        admin.check_worker_sudo()
        paths = admin_paths(admin)
        admin.provision_state(paths, worker)
        admin.install_components(source / "installer", paths, PATHS_FILE)
        _prepare_initial(nonce, paths, source)
    _activate(nonce)


def run_phase(phase, nonce, **continuation):
    if phase == "readiness-only":
        from scripts.nested_fixture_repair import readiness_only

        return readiness_only(sys.modules[__name__], nonce, **continuation)
    if phase == "repair-environmentfile":
        raise ValueError("Installed repair checkpoint consumed; repair cannot be repeated")
    handlers = {"bootstrap": bootstrap, "probe": probe, "resume-after-sudo": resume_after_sudo}
    if phase not in handlers:
        raise ValueError("Unsupported nested fixture phase")
    require_guest(nonce)
    return handlers[phase](nonce, **continuation)
