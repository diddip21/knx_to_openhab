#!/usr/bin/env python3
"""Safely set the Web UI password stored in the external secrets file."""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import re
import shlex
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

PASSWORD_KEY = "KNXOH_UI_PASSWORD_HASH_B64"
LEGACY_PASSWORD_KEY = "KNXOH_UI_PASSWORD_B64"
DEFAULT_PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")


def hash_password(password):
    # Only the unprivileged mode imports dependencies from the application venv.
    from argon2 import PasswordHasher

    if len(password) < 12:
        raise ValueError("Choose a Web UI password with at least 12 characters")
    return PasswordHasher(
        time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16
    ).hash(password)


def validate_hash(value):
    """Strict data boundary: exact supported Argon2id costs and canonical PHC."""
    match = re.fullmatch(
        r"\$argon2id\$v=19\$m=65536,t=3,p=2\$([A-Za-z0-9+/]{22})\$([A-Za-z0-9+/]{43})", value
    )
    if match is None:
        raise ValueError("Expected a complete Argon2id hash from --hash-only")
    for encoded, size in zip(match.groups(), (16, 32)):
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        if len(raw) != size or base64.b64encode(raw).decode().rstrip("=") != encoded:
            raise ValueError("Noncanonical password hash")
    return value


@contextmanager
def protected_parent(path):
    """Root writer uses only stdlib and no-follow protected directory descriptors."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise ValueError("Expected an absolute protected path")
    fds = []
    chain = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        fds.append(fd)
        for component in path.parts[1:-1]:
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o7022:
                raise ValueError("Unsafe password destination ancestor")
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            chain.append((fd, component, child, os.fstat(child)))
            fds.append(child)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o7022:
            raise ValueError("Unsafe password destination directory")

        def check():
            for parent, name, child, expected in chain:
                for actual in (
                    os.fstat(child),
                    os.stat(name, dir_fd=parent, follow_symlinks=False),
                ):
                    if identity(actual) != identity(expected):
                        raise ValueError("Password destination ancestor changed")

        yield fd, path.name, check
    finally:
        for fd in reversed(fds):
            os.close(fd)


def identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink


def read_protected(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_nlink != 1
            or info.st_mode & 0o7022
            or info.st_size > 65536
        ):
            raise ValueError("Unsafe password settings file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(65537)
        after = os.fstat(fd)
        if (
            len(raw) > 65536
            or identity(after) != identity(info)
            or (after.st_mtime_ns, after.st_ctime_ns) != (info.st_mtime_ns, info.st_ctime_ns)
        ):
            raise ValueError("Password settings changed while reading")
        return raw.decode("utf-8"), info
    finally:
        os.close(fd)


def replace_hash(raw, password_hash):
    encoded = base64.b64encode(validate_hash(password_hash).encode()).decode("ascii")
    updated = []
    inserted = False
    for line in raw.splitlines():
        if line.partition("=")[0].strip() in (PASSWORD_KEY, LEGACY_PASSWORD_KEY):
            if not inserted:
                updated.append(f"{PASSWORD_KEY}={encoded}")
                inserted = True
        else:
            updated.append(line)
    if not inserted:
        updated.append(f"{PASSWORD_KEY}={encoded}")
    return "\n".join(updated) + "\n"


def write_password_hash(secrets_file, password_hash):
    validate_hash(password_hash)  # Reject untrusted data BEFORE opening any destination.
    with protected_parent(secrets_file) as (parent, name, check):
        raw, info = read_protected(parent, name)
        if stat.S_IMODE(info.st_mode) not in (0o600, 0o640):
            raise ValueError("Secrets must have mode 0600 or 0640")
        temporary = ".password-" + os.urandom(16).hex()
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        replaced = False
        try:
            os.fchown(fd, info.st_uid, info.st_gid)
            os.fchmod(fd, 0o640)
            with os.fdopen(os.dup(fd), "w", encoding="utf-8") as stream:
                stream.write(replace_hash(raw, password_hash))
                stream.flush()
                os.fsync(stream.fileno())
            check()
            if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(info):
                raise ValueError("Secrets destination changed")
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            replaced = True
            os.fsync(parent)
        finally:
            os.close(fd)
            if not replaced:
                os.unlink(temporary, dir_fd=parent)


def configured_secrets_file(paths_file: Path | None = None) -> Path:
    """Resolve the external secrets file using the installer's data-only format."""
    configured_paths_file = (
        paths_file
        if paths_file is not None
        else os.environ.get("KNXOH_PATHS_FILE", str(DEFAULT_PATHS_FILE))
    )
    paths_file = Path(configured_paths_file)
    for line in paths_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("KNXOH_CONFIG_DIR="):
            continue
        values = shlex.split(line.split("=", 1)[1], posix=True)
        if len(values) == 1:
            return Path(values[0]) / "secrets.env"
        break
    raise ValueError(f"No KNXOH_CONFIG_DIR entry found in {paths_file}")


def set_ui_password(secrets_file: Path, password: str) -> None:
    """Replace the encoded password while preserving the secret file's owner."""
    if len(password) < 12:
        raise ValueError("Choose a Web UI password with at least 12 characters")

    secrets_file = Path(secrets_file)
    info = secrets_file.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"The secrets path must be a regular file: {secrets_file}")

    lines = secrets_file.read_text(encoding="utf-8").splitlines()
    password_hash = hash_password(password)
    encoded = base64.b64encode(password_hash.encode("utf-8")).decode("ascii")
    replacement = f"{PASSWORD_KEY}={encoded}"
    updated = []
    inserted = False
    for line in lines:
        name = line.partition("=")[0].strip()
        if name in (PASSWORD_KEY, LEGACY_PASSWORD_KEY):
            if not inserted:
                updated.append(replacement)
                inserted = True
            continue
        updated.append(line)
    if not inserted:
        updated.append(replacement)

    fd, temporary_name = tempfile.mkstemp(prefix=".secrets-", dir=secrets_file.parent)
    try:
        os.fchown(fd, info.st_uid, info.st_gid)
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w", encoding="utf-8") as destination:
            destination.write("\n".join(updated) + "\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, secrets_file)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-file", type=Path)
    parser.add_argument("--paths-file", type=Path, default=DEFAULT_PATHS_FILE)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--hash-only", action="store_true")
    modes.add_argument("--hash-stdin", action="store_true")
    args = parser.parse_args()

    if args.hash_stdin:
        if os.name != "posix" or os.geteuid() != 0 or not sys.flags.isolated:
            parser.error("The strict writer requires root and /usr/bin/python3 -I")
        try:
            password_hash = validate_hash(sys.stdin.read(513).removesuffix("\n"))
            secrets_file = args.secrets_file
            if secrets_file is None:
                with protected_parent(args.paths_file) as (parent, name, check):
                    raw, _ = read_protected(parent, name)
                    check()
                values = [
                    shlex.split(line.split("=", 1)[1])
                    for line in raw.splitlines()
                    if line.startswith("KNXOH_CONFIG_DIR=")
                ]
                if len(values) != 1 or len(values[0]) != 1:
                    raise ValueError("Invalid protected paths contract")
                secrets_file = Path(values[0][0]) / "secrets.env"
            write_password_hash(secrets_file, password_hash)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(f"Web UI Argon2id password hash updated in {secrets_file}.")
        print("Restart the service with: sudo systemctl restart knxohui.service")
        return 0
    if os.name == "posix" and os.geteuid() == 0:
        parser.error(
            "Never hash through an application venv as root; use unprivileged --hash-only and the strict --hash-stdin writer"
        )

    if args.hash_only:
        password = getpass.getpass("New Web UI password: ")
        if password != getpass.getpass("Confirm new Web UI password: "):
            parser.error("passwords did not match")
        try:
            print(hash_password(password))
        except ValueError as error:
            parser.error(str(error))
        return 0

    try:
        secrets_file = args.secrets_file or configured_secrets_file()
    except (OSError, ValueError) as error:
        parser.error(str(error))

    password = getpass.getpass("New Web UI password: ")
    confirmation = getpass.getpass("Confirm new Web UI password: ")
    if password != confirmation:
        parser.error("passwords did not match")

    try:
        set_ui_password(secrets_file, password)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Web UI Argon2id password hash updated in {secrets_file}.")
    print("Restart the service with: sudo systemctl restart knxohui.service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
