#!/usr/bin/env python3
"""Regenerate golden files for output validation tests."""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ets_to_openhab
import knxproject_to_openhab
from config import config

TESTS_DIR = os.path.join(os.path.dirname(__file__), "..", "tests")
EXPECTED_OUTPUT_DIR = os.path.join(TESTS_DIR, "fixtures", "expected_output")
SHARED_PERSIST_PATH = os.path.join(EXPECTED_OUTPUT_DIR, "common", "influxdb.persist")
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

    original_config = {
        key: config.get(key)
        for key in (
            "output_format",
            "openhab_path",
            "items_path",
            "things_path",
            "sitemaps_path",
            "influx_path",
            "fenster_path",
            "yaml_path",
        )
    }
    with tempfile.TemporaryDirectory(prefix="knx-golden-") as output_dir:
        config["output_format"] = "legacy"
        config["openhab_path"] = output_dir
        config["items_path"] = os.path.join(output_dir, "knx.items")
        config["things_path"] = os.path.join(output_dir, "knx.things")
        config["sitemaps_path"] = os.path.join(output_dir, "knx.sitemap")
        config["influx_path"] = os.path.join(output_dir, "influxdb.persist")
        config["fenster_path"] = os.path.join(output_dir, "fenster.rules")
        config["yaml_path"] = os.path.join(output_dir, "knx.yaml")
        try:
            ets_to_openhab.export_output(
                items,
                sitemap,
                things,
                include_private_persistence=False,
            )
        finally:
            for key, value in original_config.items():
                if value is None:
                    config.pop(key, None)
                else:
                    config[key] = value

        for filename in ("knx.items", "knx.things", "knx.sitemap"):
            shutil.copyfile(os.path.join(output_dir, filename), os.path.join(golden_dir, filename))

        persist_source = os.path.join(output_dir, "influxdb.persist")
        with open(persist_source, encoding="utf-8") as f:
            persist_content = f.read()

    case_persist_path = os.path.join(golden_dir, "influxdb.persist")
    if case_name == "Charne":
        os.makedirs(os.path.dirname(SHARED_PERSIST_PATH), exist_ok=True)
        with open(SHARED_PERSIST_PATH, "w", encoding="utf-8") as f:
            f.write(persist_content)
        if os.path.exists(case_persist_path):
            os.remove(case_persist_path)
    elif os.path.exists(SHARED_PERSIST_PATH):
        with open(SHARED_PERSIST_PATH, encoding="utf-8") as f:
            shared_persist_content = f.read()
        if persist_content == shared_persist_content:
            if os.path.exists(case_persist_path):
                os.remove(case_persist_path)
        else:
            with open(case_persist_path, "w", encoding="utf-8") as f:
                f.write(persist_content)
    else:
        with open(case_persist_path, "w", encoding="utf-8") as f:
            f.write(persist_content)

    sizes = {
        name: os.path.getsize(os.path.join(golden_dir, name))
        for name in ("knx.items", "knx.things", "knx.sitemap")
    }
    print(
        f"{case_name}: items={sizes['knx.items']}b things={sizes['knx.things']}b "
        f"sitemap={sizes['knx.sitemap']}b persist={len(persist_content.encode('utf-8'))}b"
    )


if __name__ == "__main__":
    for case_name, project_path in CASES:
        generate(case_name, project_path)
