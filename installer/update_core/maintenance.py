"""Application-independent admission protocol for the trusted updater bundle.

Installer provisions LEASE_NAME as root:knxohui 0660 in protected CONFIG_DIR.
Never create, replace, truncate or unlink that inode. Group write permission is
only a lease capability, not authority to publish intent or updater state.
Coordinator callers already hold the host lifecycle lock. Keep the returned
quiescence handle through stop, migration, activation, readiness and rollback.
"""

from __future__ import annotations

import math
import os
import stat
import time
from contextlib import ExitStack, contextmanager
from uuid import UUID

from . import secure_fs as fs

LEASE_NAME = ".updater-mutation.lock"
INTENT_NAME = ".updater-maintenance.json"


class MaintenanceError(RuntimeError):
    """Mutation unavailable; retry after maintenance or repair protected setup."""


def _config(paths):
    if paths.config_dir is None:
        raise ValueError("Missing protected CONFIG_DIR")
    return fs._canonical(paths.config_dir)


def maintenance_requested(paths) -> bool:
    """Any protected intent blocks admission; unsafe/unreadable intent fails closed."""
    try:
        fs.read_regular(_config(paths) / INTENT_NAME, 4096)
    except FileNotFoundError:
        return False
    return True


@contextmanager
def _lease_fd(paths):
    # This narrow exception to secure_fs's no-group-writers rule applies ONLY to
    # this inert inode. All parents and all root-authoritative files stay strict.
    with fs._parent(_config(paths) / LEASE_NAME) as (stack, parent, name, chain):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != 0o660
            or before.st_nlink != 1
        ):
            raise ValueError("Unsafe provisioned mutation lease")
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent
        )
        stack.callback(os.close, fd)
        entry = fs._Entry(fd, parent, name, before, same_mount=True)
        fs._check([*chain, entry])
        yield fd
        fs._check([*chain, entry])


@contextmanager
def mutation_lease(paths):
    """Acquire shared first, THEN inspect intent: atomic cross-worker admission."""
    with ExitStack() as stack:
        try:
            import fcntl

            fd = stack.enter_context(_lease_fd(paths))
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            if maintenance_requested(paths):
                raise MaintenanceError("Release maintenance in progress; retry later")
        except (OSError, ValueError, NotImplementedError, ImportError) as error:
            raise MaintenanceError(
                "Release maintenance or unsafe/missing mutation lease; retry or repair installation"
            ) from error
        yield


def _intent_data(request_id=None):
    if request_id is None:
        return b'{"maintenance":true}'
    if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
        raise ValueError("Expected canonical maintenance request UUID")
    return b'{"maintenance":true,"request_id":"' + request_id.encode("ascii") + b'"}'


def _clear_intent(paths, expected_data=None):
    with fs._parent(_config(paths) / INTENT_NAME) as (stack, parent, name, chain):
        try:
            entry = fs._open(stack, parent, name, {0}, os.fstat(parent).st_dev)
        except FileNotFoundError:
            fs._check(chain)
            # Retry an unlink whose directory fsync failed: observed absence
            # alone is not proof of durable cleanup.
            os.fsync(parent)
            return
        if (
            expected_data is not None
            and fs.read_regular(_config(paths) / INTENT_NAME, 4096) != expected_data
        ):
            raise MaintenanceError(
                "Unrelated maintenance intent retained; explicit recovery required"
            )
        fs._check([*chain, entry])
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)


def clear_request_intent(paths, request_id: str):
    """Root caller holds lifecycle lock; clear ONLY this request or sync absence.

    This is not lease acquisition and must not stop existing writers. Untagged,
    malformed, unsafe or differently tagged intent is retained for recovery.
    """
    if request_id is None:
        raise ValueError("A request UUID is required for request-specific cleanup")
    _clear_intent(paths, _intent_data(request_id))


class _Quiescence:
    def __init__(self, paths, lease, intent_data):
        self.paths = paths
        self.lease = lease
        self.intent_data = intent_data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Caller must not leave this scope until coherent commit/rollback. A
        # crashed coordinator leaves durable intent denying further mutations.
        try:
            if exc[0] is None:
                _clear_intent(self.paths, self.intent_data)
        finally:
            self.lease.__exit__(*exc)


def wait_for_quiescence(paths, timeout: float = 120.0, *, request_id: str | None = None):
    """Persist intent, drain at most 120s, return an ALREADY HELD exclusive lease.

    Use as a context manager; unlike a lazy generator, calling this interface
    itself establishes quiescence. Timeout clears intent without killing jobs.
    A coordinator request UUID tags publication for safe pre-handle reconciliation.
    """
    import fcntl

    if not math.isfinite(timeout) or not 0 <= timeout <= 120:
        raise ValueError("Drain timeout must be between 0 and 120 seconds")
    intent_data = _intent_data(request_id)
    if maintenance_requested(paths):
        raise MaintenanceError("Maintenance already requested; recover before retrying")
    lease = _lease_fd(paths)
    entered = False
    try:
        # Replacement may succeed before its directory fsync raises. Keep that
        # publication inside cleanup ownership, even before a lease FD is held.
        fs.atomic_write(_config(paths) / INTENT_NAME, intent_data, 0, 0, 0o644)
        fd = lease.__enter__()
        entered = True
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return _Quiescence(paths, lease, intent_data)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Mutation drain exceeded maintenance timeout")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    except BaseException:
        try:
            _clear_intent(paths, intent_data)
        finally:
            if entered:
                lease.__exit__(None, None, None)
        raise
