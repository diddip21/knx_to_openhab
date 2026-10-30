"""One named installed-state transition. No enrollment, bootstrap or retry fallback.

Checkpoint inputs are hash-only, externally pinned by the controller. They are
never generated/approved by this module. Nothing here executes a retained venv.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import urllib.request
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from scripts import nested_fixture_state as state

OLD_HEAD = "47e2c3a3cd59d716f793226ec17badde60999eca"
OLD_FILES_SHA256 = "34692929a224a22a53d6bd87aa48098ad98bbbcd023d2b741432f92ce3d2ea8e"
OLD_ARCHIVE_SHA256 = "1a02d8a3e89f23052aee137aa57f0f3321aa9d15da79af828368a527d2695676"
MACHINE_ID = "a50e862ca2e04dbda6720e0337e3d3da"
BOOT_ID = "4ef02c08-118a-4630-be3d-a348c9937c91"
INITIAL = PurePosixPath(state.BASE.as_posix()) / "releases/0.1.0"
LIBEXEC = PurePosixPath("/usr/local/libexec/knx_to_openhab")
SYSTEMD = PurePosixPath("/etc/systemd/system")
WRITERS = (state.UNITS[0], state.UNITS[2], state.UNITS[1])
MANAGER_FIELDS = (
    "LoadState",
    "ActiveState",
    "SubState",
    "MainPID",
    "Result",
    "ExecMainStatus",
    "NRestarts",
    "UnitFileState",
)
SOURCE_CHANGES = {
    "installer/update_bootstrap.py",
    "tests/test_update_units.py",
    "tests/integration/test_update_environment_runtime.py",
}


def validate_old_source(approval):
    root = state.validate_source_manifest(approval, OLD_HEAD)
    digest = hashlib.sha256(
        json.dumps(approval["files"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != OLD_FILES_SHA256 or approval["archive_sha256"] != OLD_ARCHIVE_SHA256:
        raise ValueError("Unknown original source approval")
    return root


def validate_source_delta(old, new):
    changed = {name for name in set(old) | set(new) if old.get(name) != new.get(name)}
    if (
        not changed <= SOURCE_CHANGES
        or "installer/update_bootstrap.py" not in changed
        or set(old) - set(new)
        or any(old[name]["mode"] != new[name]["mode"] for name in set(old) & set(new))
    ):
        raise ValueError("Unapproved repair source delta")


def _legacy_manifest(approval):
    value = copy.deepcopy(approval)
    value["purpose"] = "reviewed-sudo-fix-source"
    value["production_base"] = "27d106a26c907b7ce05d1880ea25157b1f815e50"
    return value


def validate_repair_source(approval, head, old):
    validate_old_source(old)
    if (
        not isinstance(head, str)
        or re.fullmatch(r"[0-9a-f]{40}", head) is None
        or head == OLD_HEAD
        or type(approval) is not dict
        or approval.get("purpose") != "reviewed-environmentfile-fix-source"
        or approval.get("production_base") != OLD_HEAD
    ):
        raise ValueError("Explicit new reviewed EnvironmentFile source required")
    root = state.validate_source_manifest(_legacy_manifest(approval), head)
    validate_source_delta(old["files"], approval["files"])
    return root


def verify_repair_sources(checkpoint, approval, head):
    old = checkpoint["old_source_approval"]
    validate_repair_source(approval, head, old)
    state.verify_source_approval(old, OLD_HEAD)
    return state.verify_source_approval(_legacy_manifest(approval), head)


def manager_state():
    """Fixed, read-only PID-1 queries; no app manager effects."""
    units = {}
    for unit in state.UNITS:
        raw = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                "--no-pager",
                "--property=" + ",".join(MANAGER_FIELDS),
                "--",
                unit,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        values = {}
        for line in raw.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values or key not in MANAGER_FIELDS:
                raise ValueError("Unexpected manager property")
            values[key] = value
        # Timer units lack service-only properties; normalize their absence, not
        # their actual values when returned. All other properties remain required.
        if unit.endswith(".timer"):
            for key in ("MainPID", "ExecMainStatus", "NRestarts"):
                values.setdefault(key, "0")
        units[unit] = values
    raw = subprocess.run(
        ["/usr/bin/systemctl", "list-jobs", "--all", "--no-pager", "--no-legend", "--plain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    jobs = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Unexpected manager jobs output")
        if fields[1].startswith("knxoh"):
            jobs.append(fields)
    return {"units": units, "jobs": jobs}


def validate_manager(value):
    if type(value) is not dict or set(value) != {"units", "jobs"} or value["jobs"] != []:
        raise ValueError("Unsafe manager jobs/state")
    if type(value["units"]) is not dict or set(value["units"]) != set(state.UNITS):
        raise ValueError("Incomplete manager unit state")
    for unit, properties in value["units"].items():
        if (
            type(properties) is not dict
            or set(properties) != set(MANAGER_FIELDS)
            or any(not isinstance(v, str) for v in properties.values())
            or properties["LoadState"] != "loaded"
            or properties["MainPID"] != "0"
            or any(
                re.fullmatch(r"[0-9]+", properties[k]) is None
                for k in ("NRestarts", "ExecMainStatus")
            )
        ):
            raise ValueError("Unsafe manager unit properties")
        if unit == state.UNITS[4]:
            if any(
                properties[k] != v
                for k, v in {
                    "ActiveState": "active",
                    "SubState": "exited",
                    "Result": "success",
                    "ExecMainStatus": "0",
                }.items()
            ):
                raise ValueError("Unsafe manager recovery state")
        elif (properties["ActiveState"], properties["SubState"]) not in (
            ("inactive", "dead"),
            ("failed", "failed"),
        ):
            raise ValueError("Unsafe manager writer state")


def _metadata(info):
    return dict(
        kind="directory" if stat.S_ISDIR(info.st_mode) else "file",
        uid=info.st_uid,
        gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
        links=info.st_nlink,
    )


def snapshot_tree(root, *, fs=None):
    """Stream immutable trees without following links or retaining 3354 FDs.

    Each ancestor remains pinned through recursion. A directory race or a changed
    file invalidates the entire observation, including names removed mid-scan.
    """
    if fs is None:
        from installer.update_core import secure_fs as fs

    result = {}

    def visit(parent, name, chain, device):
        with ExitStack() as stack:
            path = root if not chain else root.joinpath(*chain)
            pinned = _open_inventory(fs, stack, parent, name, path, device)
            value = _metadata(pinned.info)
            if value["kind"] == "directory":
                children = sorted(os.listdir(pinned.fd))
                value["children"] = children
                for child in children:
                    visit(pinned.fd, child, [*chain, child], pinned.info.st_dev)
                if sorted(os.listdir(pinned.fd)) != children:
                    raise ValueError("Repair tree changed during read")
            else:
                digest = hashlib.sha256()
                total = 0
                while True:
                    raw = os.read(pinned.fd, 1024 * 1024)
                    if not raw:
                        break
                    total += len(raw)
                    if total > 128 * 1024 * 1024:
                        raise ValueError("Oversized repair tree file")
                    digest.update(raw)
                value["sha256"] = digest.hexdigest()
            after = os.fstat(pinned.fd)
            if any(
                getattr(pinned.info, k) != getattr(after, k)
                for k in ("st_size", "st_mtime_ns", "st_ctime_ns")
            ):
                raise ValueError("Repair tree changed during read")
            fs._check([pinned])
            result[path.as_posix()] = value

    with fs._parent(root) as (_, parent, name, chain):
        visit(parent, name, [], None)
        fs._check(chain)
    return result


def _open_inventory(fs, stack, parent, name, path, device):
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if path == state.CONFIG / ".updater-mutation.lock":
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (
            0,
            989,
            0o660,
            1,
        ) or not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe retained mutation lock")
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
        stack.callback(os.close, fd)
        pinned = fs._Entry(fd, parent, name, info, same_mount=device is not None)
        pinned.check()
        return pinned
    owners = {0, 999} if state.OUTPUT in path.parents else {0}
    return fs._open(stack, parent, name, owners, device, directory=stat.S_ISDIR(info.st_mode))


def inventory_entry(path, *, details):
    from installer.update_core import secure_fs as fs

    value = state.entry(path, details=False)
    if value is None:
        return None
    if value["kind"] == "directory":
        return state.entry(path, details=True)
    if value["kind"] == "other":
        return value
    with fs._parent(path) as (stack, parent, name, chain):
        pinned = _open_inventory(fs, stack, parent, name, path, None)
        digest = hashlib.sha256()
        while raw := os.read(pinned.fd, 1024 * 1024):
            digest.update(raw)
        fs._check([*chain, pinned])
        after = os.fstat(pinned.fd)
        if any(
            getattr(pinned.info, k) != getattr(after, k)
            for k in ("st_size", "st_mtime_ns", "st_ctime_ns")
        ):
            raise ValueError("Fixture file changed during read")
        if value != _metadata(pinned.info):
            raise ValueError("Fixture file changed before read")
        value["sha256"] = digest.hexdigest()
        return value


def collect_installed():
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Installed inventory requires authorized nested root")
    inventory = state.collect_inventory(details=True, entry_reader=inventory_entry)
    entries = inventory["entries"]
    roots = [state.BASE / "releases", state.CONFIG, LIBEXEC, state.PREPARATION, state.OUTPUT]
    roots.extend(Path("/usr/local/libexec").glob(".knxohui-bundle-*"))
    roots.extend(SYSTEMD / (unit + ".d") for unit in state.UNITS)
    for root in roots:
        if root.as_posix() in entries:
            entries.update(snapshot_tree(root))
    for name, value in entries.items():
        if value["kind"] == "other":
            path = Path(name)
            before = path.lstat()
            if not stat.S_ISLNK(before.st_mode):
                raise ValueError("Unknown special fixture artifact")
            value["target"] = os.readlink(path)
            if path.lstat() != before:
                raise ValueError("Fixture link changed during read")
    inventory.update(
        machine_id=Path("/etc/machine-id").read_text().strip(),
        boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        manager=manager_state(),
    )
    return inventory


def _directory(entries, path, uid, gid, mode, children=None):
    value = entries.get(path.as_posix(), {})
    expected = dict(kind="directory", uid=uid, gid=gid, mode=mode)
    if children is not None:
        expected["children"] = sorted(children)
    if any(value.get(k) != v for k, v in expected.items()):
        raise ValueError("Invalid repair checkpoint directory: " + str(path))


def _systemd_enable_links():
    return {
        str(root / target / unit): str(SYSTEMD / unit)
        for root in (SYSTEMD, PurePosixPath("/usr/lib/systemd/system"))
        for target, unit in (
            ("multi-user.target.wants", state.UNITS[0]),
            ("multi-user.target.wants", state.UNITS[4]),
            ("timers.target.wants", state.UNITS[2]),
        )
    }


def _validate_systemd_entry(name, value):
    """Restrict the already collected footprint, including nested dependencies."""
    path = PurePosixPath(name)
    if not any(
        root in path.parents for root in (SYSTEMD, PurePosixPath("/usr/lib/systemd/system"))
    ):
        return
    links = _systemd_enable_links()
    if name in links:
        if any(
            value.get(k) != v
            for k, v in dict(
                kind="other",
                uid=0,
                gid=0,
                target=links[name],
            ).items()
        ):
            raise ValueError("Invalid installed systemd enable link")
        return
    drops = {
        SYSTEMD / (unit + ".d")
        for unit in (state.UNITS[0], state.UNITS[1], state.UNITS[3], state.UNITS[4])
    }
    if path in drops:
        kind = "directory"
    elif (
        path.parent == SYSTEMD
        and path.name in state.UNITS
        or path.parent in drops
        and path.name == "50-knxohui-paths.conf"
    ):
        kind = "file"
    else:
        raise ValueError("Unknown installed systemd artifact")
    if value.get("kind") != kind:
        raise ValueError("Invalid installed systemd artifact kind")


def _noncomponent_directories():
    """Exact configured roots and protected preparation, never a prefix exemption."""
    return {
        state.BASE.as_posix(): (0, 0, 0o755, ["current", "releases"]),
        (state.BASE / "releases").as_posix(): (0, 0, 0o755, ["0.1.0"]),
        state.CONFIG.as_posix(): (
            0,
            989,
            0o750,
            [
                "config.json",
                "generator.json",
                "paths.env",
                "secrets.env",
                ".updater-state",
                ".updater-mutation.lock",
                ".updater-status.json",
                ".updater-log.txt",
            ],
        ),
        state.DATA.as_posix(): (999, 989, 0o750, ["jobs", "staging", "generated"]),
        state.BACKUPS.as_posix(): (999, 989, 0o750, []),
        state.OUTPUT.as_posix(): (
            0,
            0,
            0o755,
            ["items", "things", "sitemaps", "persistence", "rules"],
        ),
        state.PREPARATION.as_posix(): (0, 988, 0o750, []),
    }


def validate_known_inventory(inventory, nonce):
    if type(inventory) is not dict or set(inventory) != {
        "entries",
        "accounts",
        "groups",
        "aliases",
        "hostname",
        "machine_id",
        "boot_id",
        "manager",
    }:
        raise ValueError("Invalid repair checkpoint inventory schema")
    if (inventory["machine_id"], inventory["boot_id"], inventory["hostname"]) != (
        MACHINE_ID,
        BOOT_ID,
        "localhost",
    ):
        raise ValueError("Repair checkpoint identity mismatch")
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
        raise ValueError("Repair checkpoint account/group mismatch")
    validate_manager(inventory["manager"])
    entries = inventory["entries"]
    if type(entries) is not dict:
        raise ValueError("Invalid repair checkpoint entries")
    for name, value in entries.items():
        if not isinstance(name, str) or type(value) is not dict:
            raise ValueError("Invalid repair checkpoint path/metadata")
        path = PurePosixPath(name)
        if not path.is_absolute() or path.as_posix() != name or ".." in path.parts:
            raise ValueError("Invalid repair checkpoint path")
        fields = {"kind", "uid", "gid", "mode", "device", "inode", "links"}
        kind = value.get("kind")
        fields.add({"file": "sha256", "directory": "children", "other": "target"}.get(kind, ""))
        if set(value) != fields or any(
            type(value[k]) is not int or value[k] < low
            for k, low in (
                ("uid", 0),
                ("gid", 0),
                ("mode", 0),
                ("device", 0),
                ("inode", 1),
                ("links", 1),
            )
        ):
            raise ValueError("Invalid repair checkpoint inode metadata")
        if kind == "file" and (
            value["links"] != 1
            or not isinstance(value["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
        ):
            raise ValueError("Invalid repair checkpoint hash/link count")
        if kind == "directory" and (
            type(value["children"]) is not list
            or any(
                not isinstance(n, str) or not n or "/" in n or n in (".", "..")
                for n in value["children"]
            )
            or value["children"] != sorted(set(value["children"]))
        ):
            raise ValueError("Invalid repair checkpoint children")
        _validate_systemd_entry(name, value)
        if kind == "other":
            allowed = {(state.BASE / "current").as_posix(): str(INITIAL), **_systemd_enable_links()}
            if value["uid"] != 0 or value["gid"] != 0 or allowed.get(name) != value["target"]:
                raise ValueError("Unknown repair checkpoint link")
    # Original hashes/modes/account identities are NOT replaced by a newly
    # collected snapshot. Only the installed layout extensions below are allowed.
    original = state.recorded_specs(nonce)
    for path in (
        state.CONFIG / "config.json",
        state.CONFIG / "generator.json",
        state.PATHS_FILE,
        Path("/etc/hosts"),
        state.RECEIPT,
        state.LOCK,
    ):
        if any(
            entries.get(path.as_posix(), {}).get(k) != v
            for k, v in original[path.as_posix()].items()
        ):
            raise ValueError("Original repair checkpoint contract changed: " + str(path))
    for name, policy in _noncomponent_directories().items():
        _directory(entries, PurePosixPath(name), *policy)
    for path in (state.DATA / n for n in ("jobs", "staging", "generated")):
        _directory(entries, path, 999, 989, 0o750, [])
    output_files = {
        "items": "knx.items",
        "things": "knx.things",
        "sitemaps": "knx.sitemap",
        "persistence": "influxdb.persist",
        "rules": "fenster.rules",
    }
    for folder, name in output_files.items():
        _directory(entries, state.OUTPUT / folder, 0, 0, 0o755, [name])
        path = (state.OUTPUT / folder / name).as_posix()
        if any(
            entries.get(path, {}).get(k) != v
            for k, v in dict(
                kind="file",
                uid=999,
                gid=989,
                mode=0o644,
                links=1,
                sha256=hashlib.sha256(b"").hexdigest(),
            ).items()
        ):
            raise ValueError("Original repair checkpoint generated output changed")
    _directory(entries, state.CONFIG / ".updater-state", 0, 0, 0o700, [])
    for path, gid, mode in (
        (state.CONFIG / "secrets.env", 989, 0o640),
        (Path("/root/knxoh-acceptance-login.json"), 0, 0o600),
        (state.CONFIG / ".updater-mutation.lock", 989, 0o660),
        (state.CONFIG / ".updater-status.json", 0, 0o644),
        (state.CONFIG / ".updater-log.txt", 0, 0o644),
    ):
        if any(
            entries.get(path.as_posix(), {}).get(k) != v
            for k, v in dict(kind="file", uid=0, gid=gid, mode=mode, links=1).items()
        ):
            raise ValueError("Unsafe repair checkpoint credentials/lock")
    if entries.get((state.BASE / "current").as_posix(), {}).get("target") != str(INITIAL):
        raise ValueError("Repair checkpoint current target changed")
    initial = {
        p: v
        for p, v in entries.items()
        if PurePosixPath(p) == INITIAL or INITIAL in PurePosixPath(p).parents
    }
    if len(initial) != 3354 or str(INITIAL / "venv") not in initial:
        raise ValueError("Repair checkpoint requires full initial 3354-entry environment")
    for value in initial.values():
        if (
            value["uid"] != 0
            or value["gid"] != 0
            or value["mode"] & 0o7022
            or value["kind"] == "other"
        ):
            raise ValueError("Unsafe repair checkpoint initial environment")
    # Disallow defaults and unknown prefixed artifacts even if snapshot approved.
    for name in entries:
        path = PurePosixPath(name)
        if name.startswith(
            (
                "/opt/knx_to_openhab",
                "/etc/knx_to_openhab",
                "/var/lib/knx_to_openhab",
                "/var/backups/knx_to_openhab",
                "/usr/lib/systemd/system/knxoh",
            )
        ):
            raise ValueError("Unexpected repair checkpoint default artifact")
        if path.name.startswith(".knxohui-bundle-"):
            raise ValueError("Unexpected retained repair checkpoint bundle")


def validate_repair_checkpoint(checkpoint, actual, nonce):
    if type(checkpoint) is not dict or set(checkpoint) != {
        "format",
        "checkpoint",
        "nonce_sha256",
        "old_source_approval",
        "inventory",
    }:
        raise ValueError("Invalid repair checkpoint schema")
    if (
        type(checkpoint["format"]) is not int
        or checkpoint["format"] != 1
        or checkpoint["checkpoint"] != "environmentfile-installed-20261030"
        or checkpoint["nonce_sha256"] != hashlib.sha256(nonce.encode()).hexdigest()
    ):
        raise ValueError("Repair checkpoint name/receipt mismatch")
    validate_old_source(checkpoint["old_source_approval"])
    validate_known_inventory(checkpoint["inventory"], nonce)
    if checkpoint["inventory"] != actual:
        raise ValueError("Pinned repair checkpoint mismatch")


def _component_files(admin, source):
    expected = {}
    for name in (*admin.BUNDLE, *admin.HELPERS):
        mode = 0o755 if name.endswith(".sh") or name == "set_ui_password.py" else 0o644
        expected[str(LIBEXEC / name)] = ((source / "installer" / name).read_bytes(), mode)
    for name in admin.UNITS:
        expected[str(SYSTEMD / name)] = ((source / "installer" / name).read_bytes(), 0o644)
    for name, text in admin.render_dropins(
        admin.Paths(
            state.BASE / "releases", state.BASE / "current", state.CONFIG, state.DATA, state.BACKUPS
        ),
        state.PATHS_FILE,
    ).items():
        expected[str(SYSTEMD / (name + ".d") / "50-knxohui-paths.conf")] = (text.encode(), 0o644)
    for target, name, mode in (
        ("/etc/sudoers.d/knxohui", "knxohui.sudoers", 0o440),
        ("/usr/local/sbin/knxohui-service-update", "service_update.sh", 0o755),
        ("/etc/tmpfiles.d/knxohui.conf", "knxohui-tmpfiles.conf", 0o644),
    ):
        expected[target] = ((source / "installer" / name).read_bytes(), mode)
    return expected


def _validate_component_bytes(inventory, expected):
    entries = inventory["entries"]
    for name, (raw, mode) in expected.items():
        if any(
            entries.get(name, {}).get(k) != v
            for k, v in dict(
                kind="file",
                uid=0,
                gid=0,
                mode=mode,
                links=1,
                sha256=hashlib.sha256(raw).hexdigest(),
            ).items()
        ):
            raise ValueError("Installed component differs from approved source: " + name)
    roots = {LIBEXEC: 0o755}
    for name in expected:
        path = PurePosixPath(name)
        if LIBEXEC in path.parents:
            roots.update({p: 0o755 for p in path.parents if p == LIBEXEC or LIBEXEC in p.parents})
        if path.parent.name.endswith(".d"):
            roots[path.parent] = 0o755
    for root, mode in roots.items():
        children = {
            PurePosixPath(p).relative_to(root).parts[0]
            for p in set(expected) | {str(p) for p in roots}
            if PurePosixPath(p) != root and root in PurePosixPath(p).parents
        }
        _directory(entries, root, 0, 0, mode, children)
    allowed = set(expected) | {str(p) for p in roots}
    noncomponents = _noncomponent_directories()
    for name in entries:
        _validate_systemd_entry(name, entries[name])
        path = PurePosixPath(name)
        if name in noncomponents:
            _directory(entries, path, *noncomponents[name])
            continue
        if (
            path == LIBEXEC
            or LIBEXEC in path.parents
            or path.name.startswith("knxoh")
            and path.parent
            in (
                SYSTEMD,
                PurePosixPath("/etc/sudoers.d"),
                PurePosixPath("/etc/tmpfiles.d"),
                PurePosixPath("/usr/local/sbin"),
                PurePosixPath("/var/lib"),
            )
        ):
            if name not in allowed:
                raise ValueError("Unknown installed component")


def validate_installed_components(fixture, checkpoint, inventory):
    old = checkpoint["old_source_approval"]
    source = validate_old_source(old)
    admin = fixture.load_approved_admin(source)
    _validate_component_bytes(inventory, _component_files(admin, source))
    entries = inventory["entries"]
    source_files = {}
    for name, value in entries.items():
        path = PurePosixPath(name)
        if INITIAL in path.parents:
            relative = path.relative_to(INITIAL)
            if relative.parts[0] != "venv" and value["kind"] == "file":
                source_files[relative.as_posix()] = {k: value[k] for k in ("sha256", "mode")}
    if source_files != old["files"]:
        raise ValueError("Initial source differs from retained old production")


def _replaceable(name):
    path = PurePosixPath(name)
    return (
        path == LIBEXEC
        or LIBEXEC in path.parents
        or path.parent == SYSTEMD
        and path.name in state.UNITS
        or path.parent.parent == SYSTEMD
        and path.parent.name in {u + ".d" for u in state.UNITS}
        and path.name == "50-knxohui-paths.conf"
        or name
        in (
            "/etc/sudoers.d/knxohui",
            "/usr/local/sbin/knxohui-service-update",
            "/etc/tmpfiles.d/knxohui.conf",
        )
    )


def verify_preserved(before, after):
    def external(value):
        result = copy.deepcopy(value)
        result["entries"] = {
            p: v
            for p, v in result["entries"].items()
            if not _replaceable(p)
            and not any(part.startswith(".knxohui-bundle-") for part in PurePosixPath(p).parts)
        }
        return result

    if external(before) != external(after):
        raise ValueError("Repair preserved state changed")


def verify_repaired(fixture, before, after, source, admin):
    _validate_component_bytes(after, _component_files(admin, source))
    prior = {
        p: v
        for p, v in before["entries"].items()
        if p == str(LIBEXEC) or LIBEXEC in PurePosixPath(p).parents
    }
    retained = {
        PurePosixPath(p).parts[4]
        for p in after["entries"]
        if p.startswith("/usr/local/libexec/.knxohui-bundle-")
    }
    if len(retained) != 1:
        raise ValueError("Expected exactly one retained previous trusted bundle")
    root = PurePosixPath("/usr/local/libexec") / retained.pop()
    old = {}
    for name, value in prior.items():
        key = str(root / PurePosixPath(name).relative_to(LIBEXEC))
        old[key] = dict(value)
        if name == str(LIBEXEC):
            old[key]["mode"] = 0o700
    actual = {
        p: v
        for p, v in after["entries"].items()
        if PurePosixPath(p) == root or root in PurePosixPath(p).parents
    }
    if old != actual:
        raise ValueError("Retained previous bundle content/inodes changed")


def health():
    # No proxy/environment injection, redirects or credential-bearing requests.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open("http://127.0.0.1:8085/health", timeout=10) as response:
        if response.status != 200 or len(response.read(65537)) > 65536:
            raise ValueError("Actual installed HTTP readiness failed")


def activate_repaired(fixture, nonce, admin):
    fixture.require_guest(nonce)
    try:
        admin.activate_services(
            dict(ui_enable=False, ui_start=True, cleanup_enable=False, cleanup_start=True),
            fixture.command,
        )
        actual = manager_state()
        print("REPAIR activation manager state", json.dumps(actual, sort_keys=True), flush=True)
        recovery = actual["units"][state.UNITS[4]]
        if any(
            recovery.get(k) != v
            for k, v in {
                "ActiveState": "active",
                "SubState": "exited",
                "Result": "success",
                "ExecMainStatus": "0",
            }.items()
        ):
            raise ValueError("Actual installed recovery failed")
        if actual["jobs"]:
            raise ValueError("Actual installed activation has queued jobs")
        for unit in (state.UNITS[0], state.UNITS[2]):
            if actual["units"][unit]["ActiveState"] != "active":
                raise ValueError("Actual installed activation is not active")
        if actual["units"][state.UNITS[0]]["SubState"] != "running":
            raise ValueError("Actual installed notify UI not running")
        health()
    except Exception:
        # No reset-failed, rollback, retry or substitute environment. Keep the
        # original activation exception even if stopping/reporting itself fails.
        try:
            fixture.require_guest(nonce)
            fixture.command(["/usr/bin/systemctl", "stop", "--", *WRITERS])
        except Exception as error:
            print("REPAIR writer stop failed", type(error).__name__, flush=True)
        try:
            print(
                "REPAIR retained failure state",
                json.dumps(manager_state(), sort_keys=True),
                flush=True,
            )
        except Exception as error:
            print("REPAIR state query failed", type(error).__name__, flush=True)
        raise


def repair_environmentfile(fixture, nonce, checkpoint, source_approval, approved_head):
    fixture.require_guest(nonce)
    before = collect_installed()
    validate_repair_checkpoint(checkpoint, before, nonce)
    source = verify_repair_sources(checkpoint, source_approval, approved_head)
    validate_installed_components(fixture, checkpoint, before)
    admin = fixture.load_approved_admin(source)
    with fixture.resume_lease(admin, checkpoint):
        fixture.require_guest(nonce)
        locked = collect_installed()
        validate_repair_checkpoint(checkpoint, locked, nonce)
        verify_repair_sources(checkpoint, source_approval, approved_head)
        validate_installed_components(fixture, checkpoint, locked)
        admin.check_worker()
        admin.check_worker_sudo()
        try:
            admin.install_components(
                source / "installer", fixture.admin_paths(admin), state.PATHS_FILE
            )
            after = collect_installed()
            verify_preserved(before, after)
            verify_repaired(fixture, before, after, source, admin)
        except Exception as error:
            print(
                "REPAIR disk transition failed; retain artifacts, no retry:",
                type(error).__name__,
                flush=True,
            )
            raise
    activate_repaired(fixture, nonce, admin)
