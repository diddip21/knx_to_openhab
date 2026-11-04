"""Shared advisory lock for Web UI request publication and updater workers."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def update_request_lock(data_dir: Path, blocking: bool) -> Iterator[bool]:
    """Lock request state until the context exits, yielding whether acquired."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "update-request.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    locked = False
    try:
        os.fchmod(descriptor, 0o600)
        operation = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
            locked = True
        except BlockingIOError:
            yield False
            return

        yield True
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
