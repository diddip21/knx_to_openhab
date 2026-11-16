#!/usr/bin/env python3
"""Safely migrate legacy Web UI bind addresses to an explicit LAN choice."""

from __future__ import annotations

import argparse
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
    *,
    output_path: Path | None = None,
) -> bool:
    """Keep legacy external access only after confirmation; otherwise use localhost."""
    config_path = Path(config_path)
    original_contents = config_path.read_bytes()
    config_stat = config_path.stat()
    config = json.loads(original_contents)
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")
    host = str(config.get("bind_host", "127.0.0.1"))
    changed = not _is_loopback_bind(host) and not confirm_external(host)
    if changed:
        config["bind_host"] = "127.0.0.1"
    if not changed and output_path is None:
        return False

    destination = Path(output_path) if output_path is not None else config_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    contents = (
        (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if changed
        else original_contents
    )
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(contents.decode("utf-8"))
            target.flush()
            os.fsync(target.fileno())
        os.chown(temp_name, config_stat.st_uid, config_stat.st_gid)
        os.chmod(temp_name, config_stat.st_mode & 0o777)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        changed = configure_bind(args.config, output_path=args.output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    if changed:
        print("Web UI is now bound to 127.0.0.1. Configure LAN access explicitly if required.")


if __name__ == "__main__":
    main()
