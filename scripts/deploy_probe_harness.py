"""One fixed NEW probe harness only. No provider/guest receipts or app operations.

Controller must independently pin this operator before running it. Failures retain
the new partial tree/evidence; existing destinations are never adopted or removed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import types
from pathlib import Path, PurePosixPath

HEAD = "0976f1025fabfb12633174cfb5422e1c136d59a9"
TARGET = "/opt/knxoh-harness-0976f10"
ARCHIVE_SHA = "0ff17eb022f058cfb41e1284b27b1d86516561bbe46b45f4f595cc8ab7b7deaf"
MAP_SHA = "4cbd7e9ea56f3322e9b140403b49a465e0ded8bd91a3f11d3a7f4eaee28841d1"
APPROVAL_SHA = "645f294d50f33eab28bc6b19b9b213d5e01f0d325e3d94c25a74787253cecc73"
RECEIPT_SHA = "77fae5534ff26c51a920136735d4e59dcc55c3a397c895aae3424508a933ec1c"
ADOPTION_SHA = "e592462094abd5cbe1dc2fd4195cdb52b8f929f66edc5304cc7a744b8bd672d8"
PROVIDER_SHA = "0ddf4c4d5a552c487bc1e46c88d31ffe4fa5337f06db3bb86f5001e1eb3b95a1"
OLD = "/opt/knxoh-harness-d1f1848"
# Exact d1f1848 Git blobs: complete transitive LOCAL import closure of the guard.
OLD_FILES = {
    "tests/integration/test_update_systemd.py": "997238518893cb51dd5d6c74f9b0824067aba2320c8791085e425f1b5c82bd3d",
    "scripts/nested_acceptance.py": PROVIDER_SHA,
    "installer/__init__.py": "777e1e29c39dbcc92ea15cf8b82bbb8dabc16359e42df493cf58797039a2c9aa",
    "installer/update_core/__init__.py": "919b9f4307f7c56a8133cb36e99a94e6c7576f0912a5fcee8418bfe6adb1afe7",
    "installer/update_core/systemd.py": "1f53d9b0a2951ffeb373704d47df6b97d665f6a967f21d34ebac8e6c134d9e0f",
    "installer/update_core/protocol.py": "03572750f5df00aa996cf8bb60209ec1338107113d45e4ac7f097d96f474cbcc",
    "installer/update_core/secure_fs.py": "a633653c26cf6e50c2e0ae76c262dc708ae1a634329a14f07520ef92cc355fc8",
}
MAX_ARCHIVE, MAX_FILE = 16 * 1024 * 1024, 8 * 1024 * 1024
ADOPTION_SOURCE = ""  # Injected AFTER operator compilation, from pinned controller bytes.


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON field")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Invalid JSON constant")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def pinned(path, digest, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or sha(raw) != digest:
        raise ValueError("External input pin/size mismatch")
    return raw


def save_private(path, raw):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def check_member(member, seen):
    name = member.name
    if (
        not name
        or name == "."
        or PurePosixPath(name).is_absolute()
        or PurePosixPath(name).as_posix() != name
        or ".." in PurePosixPath(name).parts
        or any(ord(c) < 32 or c in "\\\x7f" for c in name)
        or name in seen
        or member.type not in (tarfile.DIRTYPE, tarfile.REGTYPE)
        or member.sparse is not None
        or member.uid != 0
        or member.gid != 0
        or member.mode not in ((0o775,) if member.isdir() else (0o664, 0o775))
        or member.size < 0
        or member.size > MAX_FILE
        or (member.isdir() and member.size != 0)
        or member.linkname
    ):
        raise ValueError("Unsafe archive member")
    seen.add(name)


def check_archive(raw, approval):
    verifier()["validate_approval"](approval)
    if len(raw) > MAX_ARCHIVE or sha(raw) != ARCHIVE_SHA:
        raise ValueError("Fixed archive/approval/map required")
    contents, directories, seen = {}, set(), set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            if len(seen) >= 298:
                raise ValueError("Too many archive entries")
            check_member(member, seen)
            if member.isdir():
                directories.add(member.name)
            else:
                value = archive.extractfile(member).read(MAX_FILE + 1)
                if len(value) != member.size:
                    raise ValueError("Incomplete archive file")
                contents[member.name] = (value, member.mode & 0o755)
    files = {n: dict(sha256=sha(b), mode=m) for n, (b, m) in contents.items()}
    parents = {p.as_posix() for n in files for p in PurePosixPath(n).parents} - {"."}
    if (
        len(files) != 269
        or len(directories) != 29
        or files != approval["files"]
        or directories != parents
    ):
        raise ValueError("Incomplete/extraneous archive inventory")
    return contents


def metadata(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def protected_read(path, limit=MAX_FILE):
    """Bootstrap ONLY the fixed old import closure, using the reviewed reader.

    Canonical, root-owned non-writable ancestors exclude unprivileged replacement;
    the pinned stdlib reader checks the opened no-follow leaf and changed reads.
    Once imported, the old secure_fs supplies the FD-held deployment parent.
    """
    path = Path(path)
    before = [(p, p.lstat()) for p in (path, *path.parents)]
    for p, info in before:
        kind = stat.S_ISREG if p == path else stat.S_ISDIR
        if not kind(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o7022:
            raise ValueError("Unsafe trusted guard/receipt path")
    raw = verifier()["read_file"](path, limit)
    for p, info in before:
        if metadata(p.lstat()) != metadata(info):
            raise ValueError("Trusted guard ancestor changed")
    return raw


def require_absent(path):
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return
    raise ValueError("Unpinned old initializer/bytecode cache")


def old_guard(receipt):
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Authorized nested root required")
    if any(
        n == "test_update_systemd" or n.split(".")[0] in ("installer", "scripts")
        for n in sys.modules
    ):
        raise ValueError("Fresh isolated interpreter required")
    for name, digest in OLD_FILES.items():
        if sha(protected_read(OLD + "/" + name)) != digest:
            raise ValueError("Old trusted guard bytes differ")
        # -B prevents writes, not reads of unpinned bytecode caches.
        path = PurePosixPath(OLD + "/" + name)
        require_absent(str(path.parent / "__pycache__"))
        search = path.parent.parent if path.name == "__init__.py" else path.parent
        module = (
            path.parent.relative_to(OLD).as_posix().replace("/", ".")
            if path.name == "__init__.py"
            else (
                "test_update_systemd" if name.startswith("tests/") else name[:-3].replace("/", ".")
            )
        )
        spec = importlib.machinery.PathFinder.find_spec(module, [str(search)])
        if (
            spec is None
            or spec.origin != str(path)
            or not isinstance(spec.loader, importlib.machinery.SourceFileLoader)
        ):
            raise ValueError("Unpinned old module loader/origin")
    # scripts is an intentional namespace, never execute a newly added initializer.
    for name in ("__init__.py", "__init__.pyc"):
        require_absent(OLD + "/scripts/" + name)
    sys.dont_write_bytecode = True
    sys.path[:0] = [OLD, OLD + "/tests/integration"]
    spec = importlib.util.find_spec("scripts")
    if spec is None or list(spec.submodule_search_locations or ()) != [OLD + "/scripts"]:
        raise ValueError("Ambient scripts namespace forbidden")
    spec = importlib.util.find_spec("test_update_systemd")
    if spec is None or spec.origin != OLD + "/tests/integration/test_update_systemd.py":
        raise ValueError("Ambient old guard selection forbidden")
    guarded = importlib.import_module("test_update_systemd")
    root_receipt = protected_read("/etc/knxoh-nested-acceptance.json", 4096)
    if sha(root_receipt) != RECEIPT_SHA or strict_json(root_receipt) != receipt:
        raise ValueError("Original root provider receipt required")
    guarded._check_virtualization("systemd-nspawn", receipt["nonce"])
    if Path("/etc/machine-id").read_text().strip() != receipt["inner_machine_id"]:
        raise ValueError("Wrong inner machine")
    for name, module in list(sys.modules.items()):
        if name == "test_update_systemd" or name.split(".")[0] in ("installer", "scripts"):
            filename = getattr(module, "__file__", None)
            if (
                name == "scripts"
                and filename is None
                and list(module.__path__) == [OLD + "/scripts"]
            ):
                continue
            relative = str(filename).removeprefix(OLD + "/")
            if relative not in OLD_FILES or filename != OLD + "/" + relative:
                raise ValueError("Wrong trusted guard origin")
    return sys.modules["installer.update_core.secure_fs"]


def extract_new(contents, fs):
    # Only the verified OLD helper; never import a helper from the new tree.
    with fs._parent(Path(TARGET)) as (stack, parent, leaf, chain):
        fs._check(chain)
        if os.fstat(parent).st_gid != 0:
            raise ValueError("Unsafe /opt group")
        os.mkdir(leaf, 0o755, dir_fd=parent)  # Existing file/link/directory ALWAYS refuses.
        root = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        stack.callback(os.close, root)
        os.fchown(root, 0, 0)
        os.fchmod(root, 0o755)
        fds = {".": root}
        links = [(parent, leaf, root)]
        dirs = {p.as_posix() for n in contents for p in PurePosixPath(n).parents} - {"."}
        for name in sorted(dirs, key=lambda n: (n.count("/"), n)):
            path = PurePosixPath(name)
            parent_fd = fds[path.parent.as_posix()]
            os.mkdir(path.name, 0o755, dir_fd=parent_fd)
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            stack.callback(os.close, fd)
            os.fchown(fd, 0, 0)
            os.fchmod(fd, 0o755)
            fds[name] = fd
            links.append((parent_fd, path.name, fd))
        for name, (raw, mode) in sorted(contents.items()):
            path = PurePosixPath(name)
            fd = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=fds[path.parent.as_posix()],
            )
            with os.fdopen(fd, "wb", buffering=0) as stream:
                remaining = memoryview(raw)
                while remaining:
                    count = stream.write(remaining)
                    if not count:
                        raise OSError("Short destination write")
                    remaining = remaining[count:]
                os.fchown(fd, 0, 0)
                os.fchmod(fd, mode)
                os.fsync(fd)
        for parent_fd, name, fd in reversed(links):
            if metadata(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != metadata(
                os.fstat(fd)
            ):
                raise ValueError("New directory changed")
            os.fsync(fd)
        os.fsync(parent)
        fs._check(chain)


def verifier():
    scope = {"__name__": "_pinned_adoption_inventory"}
    if sha(ADOPTION_SOURCE.encode()) != ADOPTION_SHA:
        raise ValueError("Inventory verifier pin mismatch")
    exec(compile(ADOPTION_SOURCE, "<pinned inventory verifier>", "exec"), scope)
    return scope


def verify_deployed(approval):
    scope = verifier()
    scope["verify_tree"](approval)  # Entire tree re-read; NO run_probe/import/callback.
    return scope


def guest_deploy(raw, approval, receipt):
    contents = check_archive(raw, approval)
    fs = old_guard(receipt)  # Original root receipt/live guard BEFORE ANY target write.
    extract_new(contents, fs)
    verify_deployed(approval)
    return dict(head=HEAD, root=TARGET, archive_sha256=ARCHIVE_SHA, files=269, verified=True)


def guest_origins(operator, approval, receipt):
    """Separate read-only command: old guard in child, new imports in fresh parent."""
    auth = (
        "__name__='_old_guard_only'\n"
        + f"exec(compile({operator!r},'<pinned operator>','exec'))\n"
        + f"ADOPTION_SOURCE={ADOPTION_SOURCE!r}\nold_guard({receipt!r})\n"
    )
    subprocess.run(
        [sys.executable, "-I", "-B", "-"],
        input=auth,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    scope = verify_deployed(approval)
    scope["refuse_cached_modules"](sys.modules)
    sys.dont_write_bytecode = True
    sys.path[:0] = [TARGET, TARGET + "/tests/integration"]
    scripts = importlib.util.find_spec("scripts")
    if scripts is None or list(scripts.submodule_search_locations or ()) != [TARGET + "/scripts"]:
        raise ValueError("Ambient new scripts namespace forbidden")
    for name, relative in (
        ("installer", "installer/__init__.py"),
        ("test_update_systemd", "tests/integration/test_update_systemd.py"),
    ):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin != TARGET + "/" + relative:
            raise ValueError("Ambient new module selection forbidden")
    harness = importlib.import_module("test_update_systemd")
    scope["verify_origins"](approval, harness)
    callback = harness.test_real_migration_child_no_live_state_sudo_or_surviving_writer
    return dict(
        head=HEAD,
        root=TARGET,
        origins_verified=True,
        module_file=harness.__file__,
        callback_filename=callback.__code__.co_filename,
        adapter_filename=harness.SystemdAdapter.__init__.__code__.co_filename,
    )


def load_provider():
    raw = pinned(Path(__file__).parent / "nested_acceptance.py", PROVIDER_SHA, MAX_FILE)
    module = types.ModuleType("_pinned_provider")
    exec(compile(raw, "<pinned provider>", "exec"), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "approval", "receipt", "evidence-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument(
        "--operator-sha256",
        required=True,
        help="Independent review pin of this operator's raw bytes",
    )
    parser.add_argument(
        "--origins-only",
        action="store_true",
        help="Separate read-only origin check; never deploy or invoke callback",
    )
    args = parser.parse_args()
    if args.approval_sha256 != APPROVAL_SHA:
        raise ValueError("Fixed external approval pin required")
    approval_raw = pinned(args.approval, args.approval_sha256, 2 * 1024 * 1024)
    approval = strict_json(approval_raw)
    raw = pinned(args.archive, ARCHIVE_SHA, MAX_ARCHIVE)
    global ADOPTION_SOURCE
    ADOPTION_SOURCE = pinned(
        Path(__file__).parent / "probe_harness_adoption.py", ADOPTION_SHA, MAX_FILE
    ).decode("utf-8")
    check_archive(raw, approval)
    receipt_raw = pinned(args.receipt, RECEIPT_SHA, 4096)
    guard = load_provider()
    receipt = guard.decode_receipt(receipt_raw.decode("utf-8"))
    guard.validate_receipt(receipt)
    operator = pinned(Path(__file__), args.operator_sha256, MAX_FILE).decode("utf-8")
    guard.validate_registration(guard.registration())
    observed = guard.preflight(receipt)
    args.evidence_dir.mkdir(mode=0o700, exist_ok=False)
    save_private(
        args.evidence_dir / "preflight.json", json.dumps(observed, sort_keys=True).encode()
    )
    program = (
        "exec(compile("
        + repr(operator)
        + ",'<pinned deployment operator>','exec'))\n"
        + f"ADOPTION_SOURCE={ADOPTION_SOURCE!r}\n"
    )
    if args.origins_only:
        program += f"result=guest_origins({operator!r},{approval!r},{receipt!r})\n"
    else:
        program += f"result=guest_deploy(base64.b64decode({base64.b64encode(raw).decode()!r},validate=True),{approval!r},{receipt!r})\n"
    program += "print(json.dumps(result,sort_keys=True))\n"
    result = subprocess.run(
        [
            "wsl.exe",
            "-d",
            guard.DISTRIBUTION,
            "--",
            "/usr/bin/systemd-run",
            "--machine=" + guard.MACHINE,
            "--wait",
            "--pipe",
            "--collect",
            "/opt/knxoh-test-venv/bin/python",
            "-I",
            "-B",
            "-",
        ],
        input="__name__='_deployment_payload'\n" + program,
        text=True,
        capture_output=True,
        timeout=180,
    )
    phase = "origins" if args.origins_only else "deployment"
    save_private(
        args.evidence_dir / (phase + ".log"),
        (result.stdout + "\nSTDERR\n" + result.stderr).encode(),
    )
    if result.returncode:
        raise RuntimeError("Deployment refused; retain partial tree and private evidence")
    record = strict_json(result.stdout)
    expected = dict(head=HEAD, root=TARGET, archive_sha256=ARCHIVE_SHA, files=269, verified=True)
    if args.origins_only:
        expected = dict(
            head=HEAD,
            root=TARGET,
            origins_verified=True,
            module_file=TARGET + "/tests/integration/test_update_systemd.py",
            callback_filename=TARGET + "/tests/integration/test_update_systemd.py",
            adapter_filename=TARGET + "/installer/update_core/systemd.py",
        )
    if record != expected:
        raise ValueError("Invalid deployment result; retain evidence")
    record.update(
        approval_sha256=APPROVAL_SHA, operator_sha256=sha(operator.encode()), files_sha256=MAP_SHA
    )
    save_private(
        args.evidence_dir / (phase + "-receipt.json"), json.dumps(record, sort_keys=True).encode()
    )
    print("Fixed harness " + phase + " verified; NO probe invoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
