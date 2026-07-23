#!/usr/bin/env python3
"""Regenerate golden files for output validation tests."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = os.path.join(os.path.dirname(__file__), "..", "tests")
CASES = [
    ("Charne", os.path.join(TESTS_DIR, "Charne.knxproj.json")),
    ("UploadJson", os.path.join(TESTS_DIR, "upload.knxprojarchive.json")),
    ("Mini", os.path.join(TESTS_DIR, "fixtures", "mini_project.json")),
]


def reset_state():
    ets_to_openhab.floors = []
    ets_to_openhab.all_addresses = []
    ets_to_openhab.used_addresses = []
    ets_to_openhab.equipments = {}
    ets_to_openhab.FENSTERKONTAKTE = []
    ets_to_openhab.export_to_influx = []
    config["general"]["FloorNameAsItIs"] = False
    config["general"]["RoomNameAsItIs"] = False
    config["general"]["addMissingItems"] = True
    knxproject_to_openhab.FloorNameAsItIs = False
    knxproject_to_openhab.RoomNameAsItIs = False
    knxproject_to_openhab.ADD_MISSING_ITEMS = True


def generate(case_name, project_path):
    reset_state()

    with open(project_path, encoding="utf-8") as f:
        project = json.load(f)

    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]["name_long"]

    items, sitemap, things = ets_to_openhab.gen_building()

    golden_dir = os.path.join(TESTS_DIR, "fixtures", "expected_output", case_name)
    os.makedirs(golden_dir, exist_ok=True)

    with open(os.path.join(golden_dir, "knx.items"), "w", encoding="utf-8") as f:
        f.write(items)
    with open(os.path.join(golden_dir, "knx.things"), "w", encoding="utf-8") as f:
        f.write(things)
    with open(os.path.join(golden_dir, "knx.sitemap"), "w", encoding="utf-8") as f:
        f.write(sitemap)

    # InfluxDB persistence
    if ets_to_openhab.export_to_influx:
        lines = [
            "Strategies {",
            '  everyMinute : "0 * * * * ?"',
            "}",
            "",
            "Items {",
        ]
        for item in ets_to_openhab.export_to_influx:
            lines.append(f"    {item} : strategy = everyMinute")
        lines.append("}")
        persist_content = "\n".join(lines) + "\n"
    else:
        persist_content = ""

    with open(os.path.join(golden_dir, "influxdb.persist"), "w", encoding="utf-8") as f:
        f.write(persist_content)

    print(f"{case_name}: items={len(items)}b things={len(things)}b sitemap={len(sitemap)}b persist={len(persist_content)}b")


if __name__ == "__main__":
    for case_name, project_path in CASES:
        generate(case_name, project_path)
