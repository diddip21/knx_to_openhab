#!/usr/bin/env python3
"""Safely set the Web UI password stored in the external secrets file."""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import shlex
import stat
import tempfile
from pathlib import Path

from argon2 import PasswordHasher

PASSWORD_KEY = "KNXOH_UI_PASSWORD_HASH_B64"
LEGACY_PASSWORD_KEY = "KNXOH_UI_PASSWORD_B64"
DEFAULT_PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


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
    password_hash = _PASSWORD_HASHER.hash(password)
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
    args = parser.parse_args()

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
