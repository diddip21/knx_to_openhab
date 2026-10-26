#!/usr/bin/env python3
"""Safely migrate legacy Web UI bind addresses to an explicit LAN choice."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable


def _is_loopback_bind(value: str) -> bool:
    host = value.strip().lower().strip("[]")
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Hostnames that do not resolve to an unambiguous loopback address are
        # treated as externally reachable and require an explicit decision.
        return False


def _confirm_external_access(host: str, terminal_path: str | Path = "/dev/tty") -> bool:
    print(
        f"The existing Web UI bind address '{host}' allows access beyond this machine. "
        "Keep LAN access? [y/N] ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    try:
        with Path(terminal_path).open("r", encoding="utf-8") as terminal:
            answer = terminal.readline()
    except OSError:
        return False
    return answer.strip().lower() in ("y", "yes")


def configure_bind(
    config_path: Path,
    confirm_external: Callable[[str], bool] = _confirm_external_access,
) -> bool:
    """Keep legacy external access only after confirmation; otherwise use localhost."""
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")
    host = str(config.get("bind_host", "127.0.0.1"))
    if _is_loopback_bind(host) or confirm_external(host):
        return False

    config["bind_host"] = "127.0.0.1"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{config_path.name}.", dir=config_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(config, target, indent=2, ensure_ascii=False)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temp_name, config_path.stat().st_mode & 0o777)
        os.replace(temp_name, config_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: configure_bind.py CONFIG.json")
    try:
        changed = configure_bind(Path(sys.argv[1]))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    if changed:
        print("Web UI is now bound to 127.0.0.1. Configure LAN access explicitly if required.")


if __name__ == "__main__":
    main()
