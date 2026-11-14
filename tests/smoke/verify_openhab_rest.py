#!/usr/bin/env python3
"""Assert openHAB actually loaded generated Items, KNX Things, channels and links.

The gateway in the Mini fixture is deliberately unreachable. Thing OFFLINE is
acceptable; absent Things, channels, or Item links are not.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8080/rest"
TIMEOUT_SECONDS = 420
POLL_SECONDS = 5


def fetch(endpoint: str):
    request = Request(BASE_URL + endpoint, headers={"Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def verify(manifest: dict) -> tuple[bool, str, dict]:
    items = fetch("/items?recursive=false")
    things = fetch("/things")
    links = fetch("/links")
    if not isinstance(items, list) or not isinstance(things, list) or not isinstance(links, list):
        return False, "openHAB REST returned a non-list collection", {}
    item_names = {item["name"] for item in items}
    by_uid = {thing["UID"]: thing for thing in things}
    link_pairs = {(link["itemName"], link["channelUID"]) for link in links}

    missing_items = sorted(set(manifest["item_names"]) - item_names)
    missing_things = sorted(set(manifest["thing_uids"]) - set(by_uid))
    target_uid = "knx:device:bridge:generic"
    thing = by_uid.get(target_uid, {})
    channel_uids = {channel["uid"] for channel in thing.get("channels", [])}
    missing_channels = sorted(
        set(target_uid + ":" + name for name in manifest["channel_names"]) - channel_uids
    )
    missing_links = sorted(
        name for name in manifest["linked_items"]
        if not any(item == name and channel in channel_uids for item, channel in link_pairs)
    )
    summary = {
        "found_items": len(item_names),
        "expected_items": len(manifest["item_names"]),
        "expected_things": manifest["thing_uids"],
        "expected_channels": len(manifest["channel_names"]),
        "thing_status": thing.get("statusInfo", {}),
        "missing_items": missing_items,
        "missing_things": missing_things,
        "missing_channels": missing_channels,
        "missing_links": missing_links,
    }
    if missing_items or missing_things or missing_channels or missing_links:
        return False, json.dumps({
            key: value for key, value in summary.items() if key.startswith("missing_")
        }), summary
    return True, "All generated openHAB Items, KNX Things, channels and links loaded", summary


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: verify_openhab_rest.py MANIFEST MODE OUTPUT_REPORT_JSON")
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = sys.argv[2]
    report_file = Path(sys.argv[3])
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error = ""
    last_summary = {}
    while time.monotonic() < deadline:
        try:
            passed, last_error, last_summary = verify(manifest)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as error:
            passed, last_error = False, f"{type(error).__name__}: {error}"
        if passed:
            report_file.write_text(
                json.dumps({"mode": mode, "status": "passed", **last_summary}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            print(f"PASS [{mode}]: {last_error}")
            print(json.dumps(last_summary, indent=2))
            return
        print(f"Waiting for openHAB [{mode}]: {last_error}", flush=True)
        time.sleep(POLL_SECONDS)
    report_file.write_text(
        json.dumps(
            {"mode": mode, "status": "failed", "reason": last_error, **last_summary},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raise SystemExit(f"FAIL [{mode}] after {TIMEOUT_SECONDS}s: {last_error}")


if __name__ == "__main__":
    main()
