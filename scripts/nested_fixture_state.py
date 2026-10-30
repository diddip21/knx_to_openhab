"""Read-only inventory and exact own-fixture checkpoint validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
from pathlib import Path

BASE = Path("/srv/knxoh acceptance app")
CONFIG = Path("/etc/knxoh acceptance config")
DATA = Path("/var/lib/knxoh acceptance data")
BACKUPS = Path("/var/backups/knxoh acceptance backups")
OUTPUT = Path("/srv/knxoh acceptance generated")
PATHS_FILE = CONFIG / "paths.env"
LOCK = Path("/run/lock/knxohui-lifecycle.lock")
PREPARATION = Path("/var/lib/knxohupdate-preparation")
RECEIPT = Path("/etc/knxoh-nested-acceptance.json")
UNITS = (
    "knxohui.service",
    "knxohui-backup-cleanup.service",
    "knxohui-backup-cleanup.timer",
    "knxohui-update.service",
    "knxohui-update-recovery.service",
)


def footprint():
    paths = {
        BASE,
        BASE / "releases",
        BASE / "current",
        CONFIG,
        DATA,
        BACKUPS,
        OUTPUT,
        PATHS_FILE,
        Path("/etc/knx_to_openhab"),
        Path("/etc/knx_to_openhab/paths.env"),
        Path("/usr/local/libexec/knx_to_openhab"),
        PREPARATION,
        Path("/etc/sudoers.d/knxohui"),
        Path("/usr/local/sbin/knxohui-service-update"),
        Path("/etc/tmpfiles.d/knxohui.conf"),
        Path("/root/knxoh-acceptance-login.json"),
        CONFIG / "secrets.env",
        CONFIG / "config.json",
        CONFIG / "generator.json",
        CONFIG / ".updater-state",
        CONFIG / ".updater-mutation.lock",
        CONFIG / ".updater-status.json",
        CONFIG / ".updater-log.txt",
    }
    paths.update(
        Path(p)
        for p in ("/opt/knx_to_openhab", "/var/lib/knx_to_openhab", "/var/backups/knx_to_openhab")
    )
    paths.update(DATA / name for name in ("jobs", "staging", "generated"))
    for root in (Path("/etc/systemd/system"), Path("/usr/lib/systemd/system")):
        for name in UNITS:
            paths.update((root / name, root / (name + ".d")))
            for target in ("multi-user.target.wants", "timers.target.wants"):
                paths.add(root / target / name)
    return paths


def entry(path, *, details=False):
    """lstat includes dangling links. No writes and no following a leaf link."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    kind = (
        "directory"
        if stat.S_ISDIR(info.st_mode)
        else "file" if stat.S_ISREG(info.st_mode) else "other"
    )
    value = dict(
        kind=kind,
        uid=info.st_uid,
        gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
        links=info.st_nlink,
    )
    if details and kind == "directory":
        value["children"] = sorted(p.name for p in path.iterdir())
    if details and kind == "file":
        from installer.update_core import secure_fs as fs

        value["sha256"] = hashlib.sha256(fs.read_regular(path, 1024 * 1024)).hexdigest()
    after = path.lstat()
    if (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("Fixture inventory changed during read")
    return value


def validate_lock(value):
    if value is not None:
        if any(
            value.get(k) != v
            for k, v in {"kind": "file", "uid": 0, "gid": 0, "mode": 0o600, "links": 1}.items()
        ) or any(
            type(value.get(k)) is not int or value[k] < minimum
            for k, minimum in (("device", 0), ("inode", 1))
        ):
            raise ValueError("Unsafe retained lifecycle lock")


def existing_ancestors(path, *, details=False):
    for parent in reversed(path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            break
        if (
            details
            and parent == DATA
            and stat.S_ISDIR(info.st_mode)
            and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (999, 989, 0o750)
        ):
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Unsafe fixture destination ancestor")


def lock_entry(*, details=False):
    from installer.update_core import secure_fs as fs
    from installer.update_core.state import LifecycleLock

    with LifecycleLock()._parent() as (stack, parent, name, chain):
        try:
            pinned = fs._open(stack, parent, name, {0}, None)
        except FileNotFoundError:
            return None
        info = pinned.info
        value = dict(
            kind="file",
            uid=info.st_uid,
            gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode),
            device=info.st_dev,
            inode=info.st_ino,
            links=info.st_nlink,
        )
        validate_lock(value)
        if details:
            raw = os.read(pinned.fd, 4097)
            if len(raw) > 4096:
                raise ValueError("Oversized fixture lifecycle lock")
            value["sha256"] = hashlib.sha256(raw).hexdigest()
        fs._check([*chain, pinned])
        after = os.fstat(pinned.fd)
        if any(
            getattr(info, field) != getattr(after, field)
            for field in ("st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise ValueError("Retained lifecycle lock changed during inventory")
        return value


def collect_inventory(*, details=False):
    import grp
    import pwd

    paths = footprint()
    # Include unexpected application-prefixed units/links and retained bundles.
    for root in (Path("/etc/systemd/system"), Path("/usr/lib/systemd/system")):
        paths.update(root.rglob("knxoh*"))
    paths.update(Path("/usr/local/libexec").glob(".knxohui-bundle-*"))
    for root in (Path("/etc/sudoers.d"), Path("/etc/tmpfiles.d"), Path("/usr/local/sbin")):
        paths.update(root.glob("knxoh*"))
    paths.update(Path("/var/lib").glob("knxohupdate*"))
    for path in paths:
        existing_ancestors(path, details=details)
    if details:
        paths.update((Path("/etc/hosts"), RECEIPT))
    entries = {}
    for path in paths:
        value = entry(path, details=details)
        if value is not None:
            entries[path.as_posix()] = value
    lock = lock_entry(details=details)
    if lock is not None:
        entries[LOCK.as_posix()] = lock
    accounts, groups, aliases = {}, {}, {}
    for name in ("knxohui", "knxohupdate"):
        try:
            account = pwd.getpwnam(name)
        except KeyError:
            pass
        else:
            accounts[name] = dict(
                uid=account.pw_uid,
                gid=account.pw_gid,
                shell=account.pw_shell,
                home=account.pw_dir,
                groups=sorted(os.getgrouplist(name, account.pw_gid)),
            )
        try:
            group = grp.getgrnam(name)
        except KeyError:
            pass
        else:
            groups[name] = dict(gid=group.gr_gid, members=sorted(group.gr_mem))
            aliases[name] = sorted(g.gr_name for g in grp.getgrall() if g.gr_gid == group.gr_gid)
    return dict(
        entries=entries,
        accounts=accounts,
        groups=groups,
        aliases=aliases,
        hostname=socket.gethostname(),
    )


def validate_fresh(inventory):
    entries = dict(inventory["entries"])
    validate_lock(entries.pop(LOCK.as_posix(), None))
    if entries or inventory["accounts"] or inventory["groups"]:
        raise ValueError("Fresh fixture has existing installation artifacts/accounts/groups")


def recorded_specs(nonce):
    from scripts import nested_acceptance as provider

    receipt = dict(
        format=1,
        provider="fresh-wsl2-nspawn",
        distribution=provider.DISTRIBUTION,
        install_location=provider.LOCATION,
        outer_machine_id="7b2bd160fe364cc89aebcbdc87a09a26",
        inner_machine_id="a50e862ca2e04dbda6720e0337e3d3da",
        machine=provider.MACHINE,
        nonce=nonce,
    )
    provider.validate_receipt(receipt)
    specs = {}

    def directory(path, uid, gid, mode, children):
        specs[path.as_posix()] = dict(
            kind="directory", uid=uid, gid=gid, mode=mode, children=sorted(children)
        )

    directory(BASE, 0, 0, 0o755, ["releases"])
    directory(BASE / "releases", 0, 0, 0o755, [])
    directory(OUTPUT, 0, 0, 0o755, [])
    directory(CONFIG, 0, 989, 0o750, ["config.json", "generator.json", "paths.env"])
    directory(DATA, 999, 989, 0o750, ["jobs", "staging", "generated"])
    directory(BACKUPS, 999, 989, 0o750, [])
    for name in ("jobs", "staging", "generated"):
        directory(DATA / name, 999, 989, 0o750, [])
    hashes = {
        CONFIG
        / "config.json": (
            989,
            0o640,
            "9b03b0c51488741d51b6a982b038cd32f5b3d09b4d6d84c925b8ca6d5594ef70",
        ),
        CONFIG
        / "generator.json": (
            989,
            0o640,
            "bd38d4c92a329e5ac4c8de12b5d7966d7aedf79625c12d89d91f15e1116c6d73",
        ),
        PATHS_FILE: (0, 0o644, "2cfc6d576156ad443b722370e15196d2d9806c0ea601939a5e83f52b4f07177d"),
        Path("/etc/hosts"): (
            0,
            0o644,
            "43828ab06a236fcc33f2430a80c0c161538c5e2100d28e9732ff16811dd148c9",
        ),
        RECEIPT: (0, 0o600, hashlib.sha256(json.dumps(receipt).encode()).hexdigest()),
    }
    for path, (gid, mode, digest) in hashes.items():
        specs[path.as_posix()] = dict(
            kind="file", uid=0, gid=gid, mode=mode, links=1, sha256=digest
        )
    specs[LOCK.as_posix()] = dict(
        kind="file", uid=0, gid=0, mode=0o600, links=1, sha256=hashlib.sha256(b"").hexdigest()
    )
    return specs


def validate_recorded_partial(inventory, nonce):
    if set(inventory) != {"entries", "accounts", "groups", "aliases", "hostname"}:
        raise ValueError("Unexpected recorded checkpoint inventory schema")
    specs = recorded_specs(nonce)
    if set(inventory["entries"]) != set(specs) or inventory["hostname"] != "localhost":
        raise ValueError("Unknown or missing recorded checkpoint paths/hostname")
    for path, expected in specs.items():
        actual = inventory["entries"][path]
        allowed = set(expected) | {"device", "inode", "links"}
        if set(actual) != allowed or any(
            type(actual[k]) is not int or actual[k] < minimum
            for k, minimum in (
                ("device", 0),
                ("inode", 1),
                ("uid", 0),
                ("gid", 0),
                ("mode", 0),
                ("links", 1),
            )
        ):
            raise ValueError("Invalid recorded checkpoint inode metadata")
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("Recorded checkpoint content/ownership/mode changed: " + path)
    accounts = {
        "knxohui": dict(
            uid=999, gid=989, groups=[989], shell="/usr/sbin/nologin", home="/nonexistent"
        ),
        "knxohupdate": dict(
            uid=997, gid=988, groups=[988], shell="/usr/sbin/nologin", home="/nonexistent"
        ),
    }
    groups = {"knxohui": dict(gid=989, members=[]), "knxohupdate": dict(gid=988, members=[])}
    if (
        inventory["accounts"] != accounts
        or inventory["groups"] != groups
        or inventory["aliases"] != {name: [name] for name in groups}
    ):
        raise ValueError("Recorded checkpoint account/group identity changed")


def checkpoint_candidate(inventory, nonce):
    validate_recorded_partial(inventory, nonce)
    return dict(
        format=1,
        checkpoint="after-sudo-denial-20261030",
        machine_id="a50e862ca2e04dbda6720e0337e3d3da",
        nonce=nonce,
        inventory=inventory,
    )


def validate_checkpoint(checkpoint, inventory, nonce):
    if type(checkpoint) is not dict or set(checkpoint) != {
        "format",
        "checkpoint",
        "machine_id",
        "nonce",
        "inventory",
    }:
        raise ValueError("Invalid pinned checkpoint schema")
    if type(checkpoint["format"]) is not int or checkpoint["format"] != 1:
        raise ValueError("Invalid checkpoint version")
    expected = checkpoint_candidate(inventory, nonce)
    if checkpoint != expected:
        raise ValueError("Pinned recorded checkpoint inode/state mismatch")


def validate_source_manifest(approval, head):
    base = "27d106a26c907b7ce05d1880ea25157b1f815e50"
    if (
        not isinstance(head, str)
        or re.fullmatch(r"[0-9a-f]{40}", head) is None
        or not int(head, 16)
        or head == base
    ):
        raise ValueError("Explicit NEW reviewed production commit required")
    fields = {
        "format",
        "purpose",
        "head",
        "production_base",
        "review_approved",
        "root",
        "archive_sha256",
        "files",
    }
    if type(approval) is not dict or set(approval) != fields:
        raise ValueError("Invalid reviewed-source manifest schema")
    root = Path("/opt") / ("knxoh-source-" + head)
    if (
        type(approval["format"]) is not int
        or approval["format"] != 1
        or approval["purpose"] != "reviewed-sudo-fix-source"
        or approval["head"] != head
        or approval["production_base"] != base
        or approval["review_approved"] is not True
        or approval["root"] != root.as_posix()
        or not isinstance(approval["archive_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", approval["archive_sha256"]) is None
    ):
        raise ValueError("Reviewed source identity/approval mismatch")
    files = approval["files"]
    if type(files) is not dict or not 5 <= len(files) <= 20000:
        raise ValueError("Invalid reviewed-source file map")
    from pathlib import PurePosixPath

    for name, value in files.items():
        if not isinstance(name, str):
            raise ValueError("Unsafe reviewed-source filename")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or str(path) != name
            or ".." in path.parts
            or name == "."
            or path.parts[0] in ("venv", ".venv", ".git")
            or "__pycache__" in path.parts
            or "\\" in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or type(value) is not dict
            or set(value) != {"sha256", "mode"}
            or not isinstance(value["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            or type(value["mode"]) is not int
            or value["mode"] not in (0o644, 0o755)
        ):
            raise ValueError("Unsafe reviewed-source file entry")
    required = {
        "installer/update_bootstrap.py",
        "installer/bootstrap_activation.py",
        "installer/update_core/__init__.py",
        "requirements.txt",
        "VERSION",
    }
    if (
        not required <= set(files)
        or files["requirements.txt"]["sha256"]
        != "836f5d08439f7a536cae171993c199821a95d1face231826a49bb0043a5829fe"
    ):
        raise ValueError("Reviewed source changed original dependency contract")
    return root


def verify_source_approval(approval, head):
    from installer.update_core import secure_fs as fs

    root = validate_source_manifest(approval, head)
    expected_files = set(approval["files"])
    expected_dirs = {"."}
    for name in expected_files:
        expected_dirs.update(p.as_posix() for p in Path(name).parents)
    with fs._parent(root) as (stack, parent, name, chain):
        pinned = fs._tree(stack, parent, name, {0})
        actual_files, actual_dirs = set(), {"."}
        for path in [root, *root.rglob("*")]:
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                actual_dirs.add(relative)
                if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o755):
                    raise ValueError("Unsafe reviewed-source directory")
            else:
                actual_files.add(relative)
                value = approval["files"].get(relative)
                if value is None or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
                    0,
                    0,
                    value["mode"],
                ):
                    raise ValueError("Unknown or unsafe reviewed-source file")
                if (
                    hashlib.sha256(fs.read_regular(path, 64 * 1024 * 1024)).hexdigest()
                    != value["sha256"]
                ):
                    raise ValueError("Reviewed-source file hash mismatch")
        if actual_files != expected_files or actual_dirs != expected_dirs:
            raise ValueError("Reviewed-source tree enumeration mismatch")
        if fs.read_regular(root / "VERSION", 64).strip() != b"0.1.0":
            raise ValueError("Initial fixture requires source version 0.1.0")
        fs._check([*chain, *pinned])
    return root
