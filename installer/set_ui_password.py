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

PASSWORD_KEY = "KNXOH_UI_PASSWORD_B64"
DEFAULT_PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")


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
    if not password:
        raise ValueError("The Web UI password must not be empty")

    secrets_file = Path(secrets_file)
    info = secrets_file.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"The secrets path must be a regular file: {secrets_file}")

    lines = secrets_file.read_text(encoding="utf-8").splitlines()
    encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
    replacement = f"{PASSWORD_KEY}={encoded}"
    updated = []
    inserted = False
    for line in lines:
        if line.startswith(f"{PASSWORD_KEY}="):
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
    print(f"Web UI password updated in {secrets_file}.")
    print("Restart the service with: sudo systemctl restart knxohui.service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
