#!/usr/bin/env python3
"""Resolve a browser URL that matches the installed Web UI bind address."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import subprocess
from pathlib import Path


def _normalize_port(port: object) -> int:
    if type(port) is int:
        normalized_port = port
    elif type(port) is str and port.isascii() and port.isdecimal():
        normalized_port = int(port)
    else:
        raise ValueError("Web UI port must be an integer from 1 to 65535")

    if not 1 <= normalized_port <= 65535:
        raise ValueError("Web UI port must be between 1 and 65535")
    return normalized_port


def resolve_web_ui_endpoint(config_path: Path, lan_ip: str) -> tuple[str, str, int]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")

    bind_host = str(config.get("bind_host") or "127.0.0.1").strip().strip("[]")
    port = _normalize_port(config.get("port", 8085))

    try:
        address = ipaddress.ip_address(bind_host)
    except ValueError:
        is_loopback = bind_host.lower() in ("localhost", "localhost.localdomain")
        is_wildcard = False
    else:
        is_loopback = address.is_loopback
        is_wildcard = address.is_unspecified

    if is_loopback:
        display_host = bind_host
        if ":" in display_host:
            display_host = f"[{display_host}]"
        return "loopback", display_host, port

    if is_wildcard:
        display_host = "<device-ip>"
        for candidate in lan_ip.split():
            try:
                candidate_address = ipaddress.ip_address(candidate.strip("[]"))
            except ValueError:
                continue
            if (
                candidate_address.version == address.version
                and not candidate_address.is_loopback
                and not candidate_address.is_link_local
                and not candidate_address.is_unspecified
            ):
                display_host = candidate.strip("[]")
                break
    else:
        display_host = bind_host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return "network", display_host, port


def _local_interface_addresses() -> set[str]:
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Could not determine the local network addresses") from error

    addresses = {"127.0.0.1", "::1"}
    for candidate in result.stdout.split():
        try:
            addresses.add(ipaddress.ip_address(candidate.split("%", 1)[0]).compressed)
        except ValueError:
            continue
    return addresses


def resolve_web_ui_health_endpoint(
    bind_host: str, port: object, local_addresses: set[str] | None = None
) -> tuple[str, int]:
    """Resolve the Web UI listener to a local address safe for an update health probe."""
    port = _normalize_port(port)

    host = str(bind_host or "127.0.0.1").strip().strip("[]")
    if host.lower() in ("localhost", "localhost.localdomain"):
        return "localhost", port

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise ValueError(f"Could not resolve Web UI bind hostname: {host}") from error

        local = local_addresses if local_addresses is not None else _local_interface_addresses()
        normalized_local: set[str] = set()
        for candidate in local:
            try:
                normalized_local.add(ipaddress.ip_address(candidate.split("%", 1)[0]).compressed)
            except ValueError:
                continue

        for result in results:
            raw_address = result[4][0]
            if not isinstance(raw_address, str):
                continue
            try:
                resolved = ipaddress.ip_address(raw_address)
                normalized = ipaddress.ip_address(raw_address.split("%", 1)[0]).compressed
            except ValueError:
                continue
            if resolved.is_loopback or normalized in normalized_local:
                return resolved.compressed, port
        raise ValueError("Web UI bind hostname does not resolve to a local address")

    if address.is_unspecified:
        return ("127.0.0.1" if address.version == 4 else "::1"), port
    if address.is_multicast:
        raise ValueError("Web UI bind address must not be multicast")
    return address.compressed, port


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--lan-ip", default="")
    args = parser.parse_args()
    mode, host, port = resolve_web_ui_endpoint(args.config, args.lan_ip)
    print(mode)
    print(host)
    print(port)


if __name__ == "__main__":
    main()
