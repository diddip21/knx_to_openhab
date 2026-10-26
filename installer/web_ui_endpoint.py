#!/usr/bin/env python3
"""Resolve a browser URL that matches the installed Web UI bind address."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path


def resolve_web_ui_endpoint(config_path: Path, lan_ip: str) -> tuple[str, str, int]:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Web UI configuration must be a JSON object")

    bind_host = str(config.get("bind_host") or "127.0.0.1").strip().strip("[]")
    port = int(config.get("port", 8085))
    if not 1 <= port <= 65535:
        raise ValueError("Web UI port must be between 1 and 65535")

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
