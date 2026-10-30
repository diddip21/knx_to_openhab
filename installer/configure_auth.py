#!/usr/bin/env python3
"""Configure a first-run Web UI password without storing it in plain text."""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import json
import os
import secrets
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web_ui.backend.auth import (  # noqa: E402
    hash_password,
    is_password_hash,
    verify_password,
)

SHIPPED_DEFAULT_PASSWORD = "logihome"


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _decode_password(encoded: str) -> str:
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("The stored legacy Web UI password is invalid") from error


def _prompt_password() -> str:
    try:
        # getpass opens /dev/tty itself for input. This stream is only used to
        # display prompts, so open it write-only; terminals are not seekable.
        with open("/dev/tty", "w", encoding="utf-8") as terminal:
            password = getpass.getpass(
                "Set a Web UI password (at least 12 characters): ", stream=terminal
            )
            confirmation = getpass.getpass("Confirm Web UI password: ", stream=terminal)
    except OSError as error:
        raise RuntimeError(
            "No interactive terminal is available. Run the password prompt from an "
            "interactive shell."
        ) from error
    if password != confirmation:
        raise ValueError("The passwords do not match")
    if len(password) < 12:
        raise ValueError("Choose a password with at least 12 characters")
    return password


def configure_auth(
    config_path: Path,
    secrets_path: Path,
    password_provider: Callable[[], str] = _prompt_password,
    on_generated_password: Callable[[str], None] | None = None,
) -> bool:
    """Ensure enabled authentication has a durable Argon2id password hash."""
    config_path = Path(config_path)
    secrets_path = Path(secrets_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")
    auth = config.setdefault("auth", {})
    if not isinstance(auth, dict):
        raise ValueError("Web UI auth configuration must be an object")

    lines = secrets_path.read_text(encoding="utf-8").splitlines() if secrets_path.exists() else []
    values = {}
    for line in lines:
        name, separator, value = line.partition("=")
        if separator:
            values[name] = value.strip()

    password_hash = None
    generated_password = None
    encoded_hash = values.get("KNXOH_UI_PASSWORD_HASH_B64")
    if encoded_hash:
        password_hash = _decode_password(encoded_hash)
        if not is_password_hash(password_hash):
            raise ValueError("The stored Web UI password hash is invalid")
        if verify_password(password_hash, SHIPPED_DEFAULT_PASSWORD):
            password_hash = None

    legacy_password = auth.pop("password", None)
    if password_hash is None:
        if legacy_password is None and values.get("KNXOH_UI_PASSWORD_B64"):
            legacy_password = _decode_password(values["KNXOH_UI_PASSWORD_B64"])
        if str(legacy_password) == SHIPPED_DEFAULT_PASSWORD:
            legacy_password = None
        if legacy_password is not None:
            password_hash = hash_password(str(legacy_password))
        elif auth.get("enabled", True):
            generated_password = password_provider()
            if len(generated_password) < 12:
                raise ValueError("Choose a password with at least 12 characters")
            password_hash = hash_password(generated_password)

    secret_lines = [
        line
        for line in lines
        if line.partition("=")[0].strip()
        not in (
            "KNXOH_UI_PASSWORD_HASH_B64",
            "KNXOH_UI_PASSWORD_B64",
            "KNXOH_SESSION_SECRET_B64",
        )
    ]
    if password_hash:
        encoded_hash = base64.b64encode(password_hash.encode("utf-8")).decode("ascii")
        secret_lines.append(f"KNXOH_UI_PASSWORD_HASH_B64={encoded_hash}")

    session_secret = values.get("KNXOH_SESSION_SECRET_B64")
    if auth.get("enabled", True) and not session_secret:
        session_secret = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    if session_secret:
        try:
            decoded_session_secret = base64.b64decode(session_secret, validate=True)
        except binascii.Error as error:
            raise ValueError("The stored session secret is invalid") from error
        if len(decoded_session_secret) < 32:
            raise ValueError("The stored session secret is invalid")
        if not any(line.startswith("KNXOH_SESSION_SECRET_B64=") for line in secret_lines):
            secret_lines.append(f"KNXOH_SESSION_SECRET_B64={session_secret}")

    if password_hash or session_secret or secret_lines != lines or not secrets_path.exists():
        _atomic_write(secrets_path, "\n".join(secret_lines) + "\n", 0o640)
    if generated_password is not None and on_generated_password is not None:
        on_generated_password(generated_password)

    if "password" in config.get("auth", {}):
        config["auth"].pop("password", None)
    if not auth.get("enabled", True) and not password_hash:
        _atomic_write(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n", 0o640)
        return False
    _atomic_write(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n", 0o640)
    return password_hash is not None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    args = parser.parse_args()
    generated_password = None

    def generate_password() -> str:
        nonlocal generated_password
        generated_password = secrets.token_urlsafe(24)
        return generated_password

    def report_generated_password(password: str) -> None:
        print(
            "A random Web UI password was generated because no usable password was "
            "configured. Save it now; it will only be shown once:\n"
            f"{password}",
            flush=True,
        )

    try:
        changed = configure_auth(
            args.config,
            args.secrets,
            password_provider=generate_password,
            on_generated_password=report_generated_password,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if not generated_password and changed:
        print("Web UI password hash is configured in the restricted secrets file.")


if __name__ == "__main__":
    main()
