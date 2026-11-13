#!/usr/bin/env python3
"""Check whether the configured Web UI address can be bound after quiescing it."""

from __future__ import annotations

import ipaddress
import json
import socket
import sys
from pathlib import Path


def check_web_port(config_path: Path) -> tuple[str, int]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")
    host = config.get("bind_host", "127.0.0.1")
    port = config.get("port", 8085)
    if isinstance(port, str) and port.isascii() and port.isdecimal():
        port = int(port)
    if not isinstance(host, str) or not host or isinstance(port, bool) or not isinstance(port, int):
        raise ValueError("Web UI bind_host and port must be a host string and integer port")
    if not 1 <= port <= 65535:
        raise ValueError("Web UI port must be between 1 and 65535")

    normalized_host = host.strip().lower().strip("[]")
    try:
        is_loopback = ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        is_loopback = normalized_host in ("localhost", "localhost.localdomain")
    hosts_to_check = [host]
    if not is_loopback:
        hosts_to_check.append("127.0.0.1")

    for bind_host in hosts_to_check:
        addresses = socket.getaddrinfo(bind_host, port, type=socket.SOCK_STREAM)
        for family, socktype, protocol, _, address in addresses:
            with socket.socket(family, socktype, protocol) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                listener.bind(address)
    return host, port


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_web_port.py CONFIG.json")
    try:
        check_web_port(Path(sys.argv[1]))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Web UI port preflight failed: {error}") from error


if __name__ == "__main__":
    main()
