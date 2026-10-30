"""Probe-only adoption boundary. Stdlib only until the entire tree is verified.

This controller payload is separately reviewed/pinned; it is NOT taken from the
mutable checkout as a substitute for the reviewed callback archive. No deployment.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import sys
from pathlib import Path

HEAD = "0976f1025fabfb12633174cfb5422e1c136d59a9"
HARNESS = Path("/opt/knxoh-harness-0976f10")
ARCHIVE_SHA256 = "0ff17eb022f058cfb41e1284b27b1d86516561bbe46b45f4f595cc8ab7b7deaf"
FILES_SHA256 = "4cbd7e9ea56f3322e9b140403b49a465e0ded8bd91a3f11d3a7f4eaee28841d1"
SOURCE_PIN = "90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea"
SOURCE_HEAD = "2dcf3078b61283a41fd1ef38e34327e4f759d5c1"
CALLBACK = "tests/integration/test_update_systemd.py"
ADAPTER = "installer/update_core/systemd.py"


def validate_approval(approval):
    expected = dict(
        format=1,
        purpose="probe-only-reviewed-harness",
        head=HEAD,
        root=HARNESS.as_posix(),
        archive_sha256=ARCHIVE_SHA256,
        review_approved=True,
    )
    if (
        type(approval) is not dict
        or set(approval) != {*expected, "files"}
        or any(approval[k] != v for k, v in expected.items())
        or type(approval["format"]) is not int
        or approval["review_approved"] is not True
        or type(approval["files"]) is not dict
        or hashlib.sha256(
            json.dumps(approval["files"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != FILES_SHA256
    ):
        raise ValueError("Exact separately approved probe harness required")
    return HARNESS


def validate_source(approval, head):
    # Original production approval serialization, not the current harness HEAD.
    if (
        head != SOURCE_HEAD
        or hashlib.sha256(
            (json.dumps(approval, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        != SOURCE_PIN
    ):
        raise ValueError("Unchanged pinned production source approval required")


def refuse_cached_modules(modules):
    if any(
        name == "test_update_systemd"
        or name.startswith("_knxoh_")
        or name.split(".")[0] in ("installer", "scripts")
        for name in modules
    ):
        raise ValueError("Fresh interpreter required; cached trusted module")


def identity(info):
    # Access time legitimately changes during these read-only checks.
    return tuple(
        getattr(info, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


def read_file(path, limit=64 * 1024 * 1024):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("Linked/nonregular harness file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("Harness file changed before read")
        raw = stream.read(limit + 1)
        if len(raw) > limit or identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("Harness file changed/oversized")
    if identity(path.lstat()) != identity(before):
        raise ValueError("Harness file changed after read")
    return raw


def verify_admin_origins(approval, admin):
    root = Path(approval["root"])
    paths = [
        Path(admin.__file__),
        Path(admin.check_worker.__code__.co_filename),
        Path(admin.activate_services.__code__.co_filename),
    ]
    paths.extend(
        Path(module.__file__)
        for name, module in list(sys.modules.items())
        if name == "_knxoh_admin" or name.startswith("_knxoh_admin.")
    )
    for path in paths:
        if root not in path.parents:
            raise ValueError("Wrong production administrator origin")
        value = approval["files"].get(path.relative_to(root).as_posix())
        if value is None or hashlib.sha256(read_file(path)).hexdigest() != value["sha256"]:
            raise ValueError("Wrong production administrator hash")


def verify_tree(approval):
    root = validate_approval(approval)
    for path in reversed((root, *root.parents)):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Unsafe harness canonical ancestor")
    expected = {".": None}
    for name, value in approval["files"].items():
        expected[name] = value
        for parent in Path(name).parents:
            expected.setdefault(parent.as_posix(), None)
    observed = {}

    def visit(path):
        info = path.lstat()
        name = path.relative_to(root).as_posix()
        if name not in expected or info.st_uid != 0 or info.st_gid != 0:
            raise ValueError("Unexpected/unsafe harness member")
        value = expected[name]
        observed[name] = info
        if value is None:
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o755:
                raise ValueError("Unsafe harness directory")
            for child in path.iterdir():
                visit(child)
        elif (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != value["mode"]
            or hashlib.sha256(read_file(path)).hexdigest() != value["sha256"]
        ):
            raise ValueError("Harness file/hash/mode/link mismatch")
        if identity(path.lstat()) != identity(info):
            raise ValueError("Harness inventory changed")

    visit(root)
    if set(observed) != set(expected):
        raise ValueError("Incomplete harness inventory")
    return root


def verify_origins(approval, harness, modules=None):
    modules = sys.modules if modules is None else modules
    callback = harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer
    if (
        harness.__file__ != str(HARNESS / CALLBACK)
        or callback.__code__.co_filename != str(HARNESS / CALLBACK)
        or harness.SystemdAdapter.__init__.__code__.co_filename != str(HARNESS / ADAPTER)
    ):
        raise ValueError("Wrong callback/adapter origin")
    for name, module in list(modules.items()):
        if name == "test_update_systemd" or name.split(".")[0] in ("scripts", "installer"):
            filename = getattr(module, "__file__", None)
            if filename is None:  # Namespace packages must have exactly the selected path.
                relative = name.replace(".", "/")
                if list(getattr(module, "__path__", ())) != [str(HARNESS / relative)]:
                    raise ValueError("Wrong trusted namespace origin")
                continue
            path = Path(filename)
            if HARNESS not in path.parents:
                raise ValueError("Wrong trusted support origin")
            value = approval["files"].get(path.relative_to(HARNESS).as_posix())
            if value is None or hashlib.sha256(read_file(path)).hexdigest() != value["sha256"]:
                raise ValueError("Trusted origin hash mismatch")


def run_probe(nonce, approval, source_approval, approved_head):
    validate_source(source_approval, approved_head)
    refuse_cached_modules(sys.modules)
    root = verify_tree(approval)  # BEFORE any installer/scripts/test module import.
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Authorized nested root required")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root), str(root / "tests/integration")]
    harness = importlib.import_module("test_update_systemd")
    fixture = importlib.import_module("scripts.nested_systemd_fixture")
    repair = importlib.import_module("scripts.nested_fixture_repair")
    verify_origins(approval, harness)
    # Deliberately do NOT call the archived fixture's old hardcoded require_guest.
    harness._check_virtualization("systemd-nspawn", nonce)
    if Path("/etc/machine-id").read_text().strip() != repair.MACHINE_ID:
        raise ValueError("Wrong application fixture machine")
    transaction = importlib.import_module("installer.update_core.transaction")
    paths = transaction.load_paths(fixture.PATHS_FILE)
    if paths != fixture.expected_paths():
        raise ValueError("Off-fixture paths contract")
    fixture.validate_probe_roots(paths)
    fixture.validate_preparation()
    source = repair.verify_probe_source(source_approval, approved_head)
    # Installed isolated helper remains production-source bytes, not harness bytes.
    from installer.update_core import secure_fs as fs

    installed = Path("/usr/local/libexec/knx_to_openhab")
    admin = fixture.load_approved_admin(source)
    verify_admin_origins(source_approval, admin)
    for relative in admin.BUNDLE:
        raw = fs.read_regular(installed / relative, 1024 * 1024)
        if (
            hashlib.sha256(raw).hexdigest()
            != source_approval["files"]["installer/" + relative]["sha256"]
        ):
            raise ValueError("Installed helper/source mismatch")
    admin.check_worker()
    admin.check_worker_sudo()  # Canonical outside-NNP policy, never replaced.
    verify_origins(approval, harness)
    callback = harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer
    print(
        "PROBE verified harness origins",
        json.dumps(
            dict(
                head=HEAD,
                root=str(root),
                module_file=harness.__file__,
                callback_filename=callback.__code__.co_filename,
                callback_sha256=approval["files"][CALLBACK]["sha256"],
                adapter_filename=harness.SystemdAdapter.__init__.__code__.co_filename,
                adapter_sha256=approval["files"][ADAPTER]["sha256"],
                production_head=approved_head,
                production_approval_sha256=SOURCE_PIN,
            ),
            sort_keys=True,
        ),
        flush=True,
    )
    callback(({}, paths))
