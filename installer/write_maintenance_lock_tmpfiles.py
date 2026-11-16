#!/usr/bin/env python3
"""Write systemd-tmpfiles rules for the configured maintenance lock."""

import argparse
import grp
import os
import stat
import tempfile
from pathlib import Path


def _escape_tmpfiles_path(path: Path) -> str:
    safe = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/_-."
    return "".join(
        "%%" if byte == ord("%") else chr(byte) if byte in safe else f"\\x{byte:02x}"
        for byte in str(path).encode()
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _validate_trusted_ancestors(lock_dir: Path) -> None:
    current = Path(lock_dir.anchor)
    for part in lock_dir.parts[1:]:
        current /= part
        try:
            directory_stat = current.lstat()
        except FileNotFoundError:
            break
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError(f"The maintenance lock ancestor is not a real directory: {current}")
        directory_mode = stat.S_IMODE(directory_stat.st_mode)
        is_root_sticky_directory = directory_stat.st_uid == 0 and bool(
            directory_mode & stat.S_ISVTX
        )
        if directory_stat.st_uid != 0 or (directory_mode & 0o022 and not is_root_sticky_directory):
            raise ValueError(
                f"The maintenance lock path has an untrusted writable ancestor: {current}"
            )


def _validate_lock_location(lock_file: Path, managed_paths=()) -> None:
    raw_path = str(lock_file)
    if (
        not lock_file.is_absolute()
        or lock_file.name == ""
        or any(part in (".", "..") for part in raw_path.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_path)
    ):
        raise ValueError("The maintenance lock file must be a safe absolute path")

    current = Path(lock_file.anchor)
    for part in lock_file.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(
                "The maintenance lock needs a dedicated path without symlink components"
            )

    if lock_file.exists():
        lock_stat = lock_file.stat(follow_symlinks=False)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
            raise ValueError("The maintenance lock file must be regular and have no hard links")

    lock_dir = lock_file.parent.resolve(strict=False)
    shared_directories = {
        Path("/"),
        Path("/tmp"),
        Path("/var/lock"),
        Path("/run/lock"),
        Path("/var/run"),
        Path("/run"),
        Path("/var"),
        Path("/var/lib"),
        Path("/var/backups"),
        Path("/var/cache"),
        Path("/var/log"),
        Path("/var/tmp"),
        Path("/var/spool"),
        Path("/var/mail"),
        Path("/var/www"),
        Path("/var/opt"),
        Path("/etc"),
        Path("/usr"),
        Path("/usr/local"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
        Path("/usr/lib"),
        Path("/usr/lib64"),
        Path("/usr/share"),
        Path("/usr/include"),
        Path("/usr/src"),
        Path("/usr/games"),
        Path("/home"),
        Path("/root"),
        Path("/opt"),
        Path("/srv"),
        Path("/mnt"),
        Path("/media"),
        Path("/boot"),
        Path("/dev"),
        Path("/proc"),
        Path("/sys"),
        Path("/run/user"),
        Path("/run/systemd"),
        Path("/run/udev"),
        Path("/run/credentials"),
    }
    if lock_dir in {path.resolve(strict=False) for path in shared_directories}:
        raise ValueError("The maintenance lock needs a dedicated parent directory")

    for managed_path in managed_paths:
        managed = Path(managed_path).resolve(strict=False)
        if _paths_overlap(lock_dir, managed):
            raise ValueError("The maintenance lock needs a dedicated parent outside managed paths")

    _validate_trusted_ancestors(lock_dir)

    try:
        expected_gid = grp.getgrnam("knxohui").gr_gid
    except KeyError as error:
        raise ValueError("The required service group 'knxohui' does not exist") from error

    if lock_dir.exists():
        try:
            directory_stat = lock_dir.stat()
        except OSError as error:
            raise ValueError(
                "The existing maintenance lock parent is not a dedicated root:knxohui 0750 directory"
            ) from error
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != 0
            or directory_stat.st_gid != expected_gid
            or stat.S_IMODE(directory_stat.st_mode) != 0o750
        ):
            raise ValueError(
                "The existing maintenance lock parent is not a dedicated root:knxohui 0750 directory"
            )


def render_config(lock_file: Path, managed_paths=()) -> str:
    _validate_lock_location(lock_file, managed_paths)

    lock_dir = lock_file.parent
    return (
        f"d {_escape_tmpfiles_path(lock_dir)} 0750 root knxohui -\n"
        f"f {_escape_tmpfiles_path(lock_file)} 0660 root knxohui -\n"
    )


def write_config(lock_file: Path, destination: Path, managed_paths=()) -> None:
    contents = render_config(lock_file, managed_paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock_file", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("managed_paths", type=Path, nargs="*")
    arguments = parser.parse_args()
    write_config(arguments.lock_file, arguments.destination, arguments.managed_paths)


if __name__ == "__main__":
    main()
