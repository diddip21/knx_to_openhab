"""Installed entrypoint; the existing standalone guard owns trusted-bundle loading.

Run /usr/bin/python3 -I /usr/local/libexec/knx_to_openhab/update_release.py.
Only a fixed sibling guard is executed; no cwd/sys.path/candidate imports. Keep
this bootstrap small rather than duplicating the guard's validated-source loader.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def _launch():
    if not sys.flags.isolated or os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Coordinator requires isolated system Python as root")
    script = Path(__file__)
    if not script.is_absolute() or ".." in script.parts:
        raise ValueError("Expected absolute installed coordinator path")
    guard = script.with_name("update_start_guard.py")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for index, component in enumerate(guard.parts[1:]):
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o7022:
                raise ValueError("Unsafe coordinator ancestor")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if index < len(guard.parts) - 2:
                flags |= os.O_DIRECTORY
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if (
            info.st_uid != 0
            or info.st_mode & 0o7022
            or info.st_nlink != 1
            or not stat.S_ISREG(info.st_mode)
        ):
            raise ValueError("Unsafe fixed coordinator loader")
        # All parents and the file are root-controlled: no unprivileged path swap
        # is possible. The guard independently validates/compiles its bundle bytes.
        os.chdir("/")
        os.execve(
            "/usr/bin/python3",
            ["/usr/bin/python3", "-I", str(guard), "--coordinator", *sys.argv[1:]],
            {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        _launch()
    except (OSError, ValueError):
        raise SystemExit(1)
else:
    # Repository-only facade; standalone privileged execution never takes it.
    from .update_core.transaction import ReleaseUpdater, UpdateResult  # noqa: F401
