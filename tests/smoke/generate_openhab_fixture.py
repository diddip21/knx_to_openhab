#!/usr/bin/env python3
"""Generate a real, synthetic ETS fixture for the openHAB runtime smoke test.

Uses the same generator entrypoints as the project regression tests, not
handwritten Item/Thing records. No private ETS files or KNX gateway are needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import ets_to_openhab  # noqa: E402
import knxproject_to_openhab  # noqa: E402
from openhab_yaml import render_yaml, validate_model  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: generate_openhab_fixture.py OUTPUT_DIR")
    target = Path(sys.argv[1]).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with (ROOT / "tests/fixtures/mini_project.json").open(encoding="utf-8") as stream:
        project = json.load(stream)
    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)
    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]
    ets_to_openhab.equipments = {}
    ets_to_openhab.used_addresses = []
    ets_to_openhab.export_to_influx = []
    ets_to_openhab.FENSTERKONTAKTE = []
    items_text, sitemap_text, things_text, model = ets_to_openhab.gen_building(
        include_yaml_model=True
    )
    validate_model(model)
    if model["version"] != 1:
        raise ValueError("Generator did not emit openHAB YAML version 1")
    yaml_text = render_yaml(model)
    if not yaml_text.strip():
        raise ValueError("Generated YAML is empty")
    (target / "knx.yaml").write_text(yaml_text, encoding="utf-8")
    # Use the production legacy export path, which adds Base, the KNX bridge,
    # and Sitemap templates. Writing raw gen_building() strings would omit them.
    import os

    os.chdir(ROOT)
    ets_to_openhab._export_legacy_model(
        items_text,
        sitemap_text,
        things_text,
        {
            "items_path": str(target / "knx.items"),
            "things_path": str(target / "knx.things"),
            "sitemaps_path": str(target / "knx.sitemap"),
        },
    )
    for name in ("knx.items", "knx.things", "knx.sitemap"):
        if not (target / name).read_text(encoding="utf-8").strip():
            raise ValueError(f"Generated {name} is empty")
    channels = model["things"]["knx:device:bridge:generic"]["channels"]
    item_names = sorted(model["items"])
    if len(item_names) < 5 or len(channels) < 3:
        raise ValueError("Mini ETS fixture generated too few Items or KNX channels")
    manifest = {
        "item_names": item_names,
        "channel_names": sorted(channels),
        "thing_uids": sorted(model["things"]),
        "linked_items": sorted(
            name for name, item in model["items"].items() if item.get("channel")
        ),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Generated {len(item_names)} Items, {len(channels)} channels, "
        f"{len(model['things'])} Things from synthetic mini_project.json"
    )


if __name__ == "__main__":
    main()
