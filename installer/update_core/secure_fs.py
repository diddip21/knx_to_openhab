"""Fail-closed POSIX filesystem primitives for the fixed privileged updater.

All ancestor directories must be root-owned and not group/other writable (even
sticky temporary directories are refused). Inputs must be canonical absolute
paths. These operations do not stop children: callers MUST stop their complete
cgroups before inspecting, freezing, or removing child output. No application or
candidate code is imported here. Windows deliberately has no insecure fallback.
"""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .protocol import Journal, Paths


def _identity(info):
    return info.st_dev, info.st_ino


def _metadata(info):
    return (
        _identity(info),
        info.st_mode,
        info.st_uid,
        info.st_gid,
        (info.st_nlink if stat.S_ISREG(info.st_mode) else None),
    )


def _mount_id(fd):
    # Linux fdinfo identifies bind mounts too, unlike st_dev. The fixed proc path
    # is kernel-owned; no release or request path participates in this read.
    try:
        with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as stream:
            lines = stream.read(4096).splitlines()
    except OSError as error:
        raise ValueError("Linux fdinfo is required for mount-boundary validation") from error
    for line in lines:
        if line.startswith("mnt_id:"):
            return int(line.split(":", 1)[1])
    raise ValueError("Missing kernel mount identity")


def _validate(info, owners, device=None, directory=False):
    if device is not None and info.st_dev != device:
        raise ValueError("Cross-device updater path")
    if info.st_uid not in owners or info.st_mode & 0o7022:
        raise ValueError("Unsafe updater ownership or mode")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Expected a directory")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Expected a singly-linked regular file")


@dataclass
class _Entry:
    fd: int
    parent: int
    name: str
    info: os.stat_result
    ancestors: tuple[_Entry, ...] = ()
    same_mount: bool = False

    def check(self):
        self._check_self()
        for ancestor in self.ancestors:
            ancestor._check_self()

    def _check_self(self):
        opened = os.fstat(self.fd)
        named = os.stat(self.name, dir_fd=self.parent, follow_symlinks=False)
        if _metadata(opened) != _metadata(self.info) or _metadata(named) != _metadata(self.info):
            raise ValueError("Raced updater directory entry")
        if self.same_mount and _mount_id(self.fd) != _mount_id(self.parent):
            raise ValueError("Updater path crosses a mount boundary")


def _open(stack, parent, name, owners, device, directory=False):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _validate(before, owners, device, directory)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    fd = os.open(name, flags, dir_fd=parent)
    stack.callback(os.close, fd)
    after = os.fstat(fd)
    _validate(after, owners, device, directory)
    entry = _Entry(fd, parent, name, before, same_mount=device is not None)
    entry.check()
    return entry


def _canonical(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or str(path) != os.path.normpath(str(path)):
        raise ValueError("Expected a canonical absolute updater path")
    if path == Path("/"):
        raise ValueError("Refusing filesystem root")
    return path


@contextmanager
def _parent(path):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise NotImplementedError("Secure updater filesystem operations require POSIX")
    path = _canonical(path)
    with ExitStack() as stack:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        stack.callback(os.close, fd)
        _validate(os.fstat(fd), {0}, directory=True)
        chain = []
        for component in path.parts[1:-1]:
            # Ancestors may legitimately include separate administrator mounts.
            # The selected parent anchors the device boundary for the operation.
            entry = _open(stack, fd, component, {0}, None, directory=True)
            chain.append(entry)
            fd = entry.fd
        yield stack, fd, path.name, chain


def _check(chain):
    for entry in chain:
        entry.check()


def read_regular(path: Path, max_bytes: int) -> bytes:
    """Read a bounded root-owned file once, rejecting links and observed races."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("Invalid read limit")
    with _parent(path) as (stack, parent, name, chain):
        entry = _open(stack, parent, name, {0}, os.fstat(parent).st_dev)
        if entry.info.st_size > max_bytes:
            raise ValueError("Updater file exceeds byte limit")
        output = bytearray()
        while len(output) <= max_bytes:
            chunk = os.read(entry.fd, min(65536, max_bytes + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        _check([*chain, entry])
        after = os.fstat(entry.fd)
        if len(output) > max_bytes or (
            entry.info.st_size,
            entry.info.st_mtime_ns,
            entry.info.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Oversized or concurrently modified updater file")
        return bytes(output)


def atomic_write(path: Path, data: bytes, uid: int, gid: int, mode: int) -> None:
    """Replace within a protected parent; fsync file and parent for durable intent."""
    if uid != 0 or type(gid) is not int or gid < 0 or mode < 0 or mode & ~0o755:
        raise ValueError("Unsafe destination ownership or permissions")
    if not isinstance(data, bytes):
        raise ValueError("Expected bytes")
    with _parent(path) as (stack, parent, name, chain):
        device = os.fstat(parent).st_dev
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            original = None
        else:
            original = _open(stack, parent, name, {0}, device)
            if _metadata(before) != _metadata(original.info):
                raise ValueError("Destination changed before updater write")
        temporary = ".updater-" + secrets.token_hex(16)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        stack.callback(os.close, fd)
        created = os.fstat(fd)
        replaced = False
        try:
            offset = 0
            while offset < len(data):
                count = os.write(fd, data[offset:])
                if count <= 0:
                    raise OSError("Updater write made no progress")
                offset += count
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
            os.fsync(fd)
            _check(chain)
            if original is not None:
                original.check()
            else:
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError("Destination appeared during updater write")
            temp = _Entry(fd, parent, temporary, os.fstat(fd), same_mount=True)
            if _identity(temp.info) != _identity(created):
                raise ValueError("Raced updater temporary file")
            temp.check()
            _validate(temp.info, {0}, device)
            if (temp.info.st_uid, temp.info.st_gid, stat.S_IMODE(temp.info.st_mode)) != (
                uid,
                gid,
                mode,
            ):
                raise ValueError("Filesystem did not apply destination metadata")
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            replaced = True
            os.fsync(parent)
        finally:
            if not replaced:
                # Never unlink an entry that replaced our exclusive temporary.
                try:
                    info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if _identity(info) == _identity(created):
                        _check(chain)
                        os.unlink(temporary, dir_fd=parent)


def _tree(stack, parent, name, owners):
    device = os.fstat(parent).st_dev
    root = _open(stack, parent, name, owners, device, directory=True)
    entries = []

    def walk(entry):
        names = sorted(os.listdir(entry.fd))
        for child in names:
            info = os.stat(child, dir_fd=entry.fd, follow_symlinks=False)
            node = _open(
                stack, entry.fd, child, owners, device, directory=stat.S_ISDIR(info.st_mode)
            )
            node.ancestors = (*entry.ancestors, entry)
            if stat.S_ISDIR(node.info.st_mode):
                walk(node)
            else:
                entries.append(node)
        entry.check()
        if sorted(os.listdir(entry.fd)) != names:
            raise ValueError("Raced updater tree contents")
        entries.append(entry)

    walk(root)
    return entries


def freeze_tree(root: Path, expected_uid: int) -> None:
    """Validate the COMPLETE stopped-child tree, then freeze via held descriptors.

    No symlinks (including venv symlinks), hardlinks, mounts, special files,
    set-ID/sticky bits, group/other writers, or unexpected owners are accepted.
    Preparation must create a copy-based venv. A failed freeze retains evidence.
    Release directories/executables become 0755, data files 0644, all root:root;
    a private worker umask must not prevent the application identity reading code.
    """
    if type(expected_uid) is not int or expected_uid < 0:
        raise ValueError("Invalid preparation owner")
    with _parent(root) as (stack, parent, name, chain):
        entries = _tree(stack, parent, name, {expected_uid})
        _check([*chain, *entries])
        for entry in entries:
            _check(chain)
            entry.check()
            os.fchown(entry.fd, 0, 0)
            mode = (
                0o755 if stat.S_ISDIR(entry.info.st_mode) or entry.info.st_mode & 0o111 else 0o644
            )
            os.fchmod(entry.fd, mode)
            entry.info = os.fstat(entry.fd)
            _validate(entry.info, {0}, os.fstat(parent).st_dev, stat.S_ISDIR(entry.info.st_mode))
            if entry.info.st_gid != 0 or stat.S_IMODE(entry.info.st_mode) != mode:
                raise ValueError("Filesystem did not freeze release metadata")
            os.fsync(entry.fd)
        os.fsync(parent)


def remove_candidate(paths: Paths, journal: Journal) -> None:
    """Delete only a stopped, journal-reserved, never-published candidate.

    The caller must load Journal from protected state, not child/UI output. Any
    ambiguous identity or unsafe descendant retains the entire tree for an admin.
    """
    if (
        journal.candidate_created is not True
        or journal.candidate_published is not False
        or journal.candidate is None
        or journal.candidate_identity is None
        or type(journal.candidate_uid) is not int
        or journal.candidate_uid < 0
    ):
        raise ValueError("Candidate lacks unpublished journal provenance")
    candidate = _canonical(journal.candidate)
    releases = _canonical(paths.releases)
    if candidate.parent != releases or candidate == _canonical(journal.prior_target):
        raise ValueError("Refusing unrelated or prior release")
    with _parent(paths.current) as (_, link_parent, link_name, link_chain):
        link_info = os.stat(link_name, dir_fd=link_parent, follow_symlinks=False)
        if not stat.S_ISLNK(link_info.st_mode) or link_info.st_uid != 0:
            raise ValueError("Unsafe current link")
        target = os.readlink(link_name, dir_fd=link_parent)
        current = Path(os.path.normpath(os.path.join(str(paths.current.parent), target)))
        if current.parent != releases or current == candidate or current != journal.prior_target:
            raise ValueError("Refusing current or ambiguous release")
        with _parent(candidate) as (stack, parent, name, chain):
            prior = _open(stack, parent, current.name, {0}, os.fstat(parent).st_dev, directory=True)
            entries = _tree(stack, parent, name, {0, journal.candidate_uid})
            if _identity(entries[-1].info) != journal.candidate_identity:
                raise ValueError("Candidate identity differs from protected journal")
            _check([*chain, *link_chain, prior, *entries])
            for entry in entries:
                _check([*chain, *link_chain, prior])
                if (
                    _identity(os.stat(link_name, dir_fd=link_parent, follow_symlinks=False))
                    != (_identity(link_info))
                    or os.readlink(link_name, dir_fd=link_parent) != target
                ):
                    raise ValueError("Current link changed during candidate removal")
                entry.check()
                if stat.S_ISDIR(entry.info.st_mode):
                    os.rmdir(entry.name, dir_fd=entry.parent)
                else:
                    os.unlink(entry.name, dir_fd=entry.parent)
                os.fsync(entry.parent)
