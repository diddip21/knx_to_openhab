#!/usr/bin/env python3
"""Check whether the configured Web UI address can be bound after quiescing it."""

from __future__ import annotations

import ipaddress
import json
import socket
import sys
from pathlib import Path


def check_web_port(config_path: Path | None) -> tuple[str, int]:
    raw_config = sys.stdin.read() if config_path is None else config_path.read_text(encoding="utf-8")
    config = json.loads(raw_config)
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

    normalized_host = host.strip()
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        normalized_host = normalized_host[1:-1]
    try:
        is_ipv6_literal = ipaddress.ip_address(normalized_host).version == 6
    except ValueError:
        is_ipv6_literal = False
    family = socket.AF_INET6 if is_ipv6_literal else socket.AF_INET
    # Gunicorn selects AF_INET6 only for a literal IPv6 bind host. For IPv4
    # literals and hostnames it binds one AF_INET endpoint, using the first
    # address returned by the resolver.
    addresses = socket.getaddrinfo(
        normalized_host,
        port,
        family=family,
        type=socket.SOCK_STREAM,
    )
    if not addresses:
        raise OSError(f"No bind address resolved for {host}")
    family, socktype, protocol, _, address = addresses[0]
    with socket.socket(family, socktype, protocol) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(address)
    return host, port


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_web_port.py CONFIG.json|-")
    try:
        config_path = None if sys.argv[1] == "-" else Path(sys.argv[1])
        check_web_port(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Web UI port preflight failed: {error}") from error


if __name__ == "__main__":
    main()
