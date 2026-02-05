"""Module for reading a knx file and generating a house structure for transfer to ets_to_openhab"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

from xknxproject.models.knxproject import KNXProject
from xknxproject.xknxproj import XKNXProj

import ets_to_openhab
from config import config, normalize_string

logger = logging.getLogger(__name__)

# Compile regular expressions once for reuse
RE_ITEM_ROOM = re.compile(config["regexpattern"]["item_Room"])
RE_ITEM_FLOOR = re.compile(config["regexpattern"]["item_Floor"])
RE_FLOOR_NAME_SHORT = re.compile(config["regexpattern"]["item_Floor_nameshort"])

ITEM_FLOOR_NAME_SHORT_PREFIX = config["general"]["item_Floor_nameshort_prefix"]
ITEM_ROOM_NAME_SHORT_PREFIX = config["general"]["item_Room_nameshort_prefix"]
UNKNOWN_FLOOR_NAME = config["general"]["unknown_floorname"]
UNKNOWN_ROOM_NAME = config["general"]["unknown_roomname"]
ADD_MISSING_ITEMS = config["general"]["addMissingItems"]
FloorNameAsItIs = config["general"]["FloorNameAsItIs"]
RoomNameAsItIs = config["general"]["RoomNameAsItIs"]


def find_floors(spaces: dict) -> list:
    """
    Suche rekursiv alle Floors/Stairways/Corridors in verschachtelten spaces.
    Wenn in Building oder BuildingPart direkt Rooms enthalten sind, wird dieses Objekt als Floor behandelt.
    """
    floors = []
    for space in spaces.values():
        if space["type"] in ("Floor", "Stairway", "Corridor"):
            floors.append(space)
        elif space["type"] in ("Building", "BuildingPart"):
            # Prüfe, ob direkt Räume enthalten sind
            has_rooms = any(
                s["type"] in ("Room", "Corridor", "Stairway")
                for s in space.get("spaces", {}).values()
            )
            if has_rooms:
                # Behandle Building/BuildingPart als Floor
                floors.append(space)
            else:
                # weiter in die nächste Ebene
                floors.extend(find_floors(space.get("spaces", {})))
    return floors


def create_building(project: KNXProject) -> list[dict[str, Any]]:
    """Create a building with all floors and rooms."""
    # get name / description from knxproj object
    # extract Groupname = "Erdgeschoss"
    # name short = EG / = EG
    # name long = =EG or =EG+RM1 ... (floorshort / floorshort+roomshort)
    #
    locations = project["locations"]
    if not locations:
        logger.error("'locations' is empty.")
        raise ValueError("'locations' is empty.")

    buildings: list[dict[str, Any]] = []
    for loc in locations.values():
        building: dict[str, Any] = {"floors": []}
        if loc["type"] in ("Building", "BuildingPart"):
            building = {
                "Description": loc["description"],
                "Group name": loc["name"],
                "name_long": loc["name"],
                "name_short": None,
                "floors": [],
            }
            buildings.append(building)
            logger.debug("Added building: %s", loc["name"])

        for floor in find_floors(loc.get("spaces", {})):
            floor_short_name, floor_long_name, floor_name_plain = get_floor_name(floor)
            floor_description = floor["description"] or floor["name"]
            floor_data = {
                "Description": floor_description,
                "Group name": floor_name_plain,
                "name_long": floor_long_name,
                "name_short": floor_short_name,
                "rooms": [],
            }
            building["floors"].append(floor_data)
            logger.debug("Added floor: %s %s", floor_description, floor["name"])

            for room in floor["spaces"].values():
                if room["type"] in ("Room", "Corridor", "Stairway"):
                    room_short_name, room_long_name, room_name_plain = get_room_name(
                        room, floor_data
                    )
                    room_description = (
                        room["description"] or room_name_plain or room["usage_text"] or room["name"]
                    )
                    room_data = {
                        "Description": room_description,
                        "Group name": room_name_plain,
                        "name_long": room_long_name,
                        "name_short": room_short_name,
                        "devices": room["devices"],
                        "Addresses": [],
                    }
                    floor_data["rooms"].append(room_data)
                    logger.debug("Added room: %s %s", room_description, room["name"])

            floor_data["name_long"] = floor_data["name_long"] or floor_data["name_short"]
            floor_data["Group name"] = floor_data["Group name"] or floor_data["name_short"]
            logger.debug("Processed floor: %s", floor_data["Description"])

    return buildings


def get_floor_name(floor):
    """Extract short name for a floor."""
    floor_name = floor["name"]
    res_floor = RE_FLOOR_NAME_SHORT.search(floor_name)
    floor_name_plain = floor["name"]
    floor_long_name = ""
    floor_short_name = ""
    if FloorNameAsItIs:
        return floor["name"], floor["name"], floor["name"]
    if res_floor:
        floor_short_name = res_floor.group(0)
        floor_name_plain = floor_name_plain.replace(res_floor.group(0), "").strip()
        if not floor_short_name.startswith(ITEM_FLOOR_NAME_SHORT_PREFIX):
            floor_short_name = ITEM_FLOOR_NAME_SHORT_PREFIX + floor_short_name
    # return ITEM_FLOOR_NAME_SHORT_PREFIX + floor_name if len(floor_name) < 6 else ITEM_FLOOR_NAME_SHORT_PREFIX + floor_name
    if not floor_long_name:
        floor_long_name = floor_short_name
    return floor_short_name, floor_long_name, floor_name_plain


def get_room_name(room, floor_data):
    """Extract short name for a room."""
    res_floor = RE_ITEM_FLOOR.search(room["name"])
    res_room = RE_ITEM_ROOM.search(room["name"])
    room_name_plain = room["name"]
    room_long_name = ""
    room_short_name = ""

    if RoomNameAsItIs:
        return room["name"], room["name"], room["name"]
    if res_floor:
        if not floor_data["name_short"]:
            floor_data["name_short"] = res_floor.group(0)
            floor_data["name_long"] = floor_data["name_short"]
        room_name_plain = room_name_plain.replace(res_floor.group(0), "").strip()
        if floor_data["name_short"] in (
            room["name"],
            ITEM_FLOOR_NAME_SHORT_PREFIX + room["name"],
        ):
            floor_data["name_short"] = res_floor.group(0)
            floor_data["Description"] = room["name"].replace(res_floor.group(0), "").strip()

    if res_room:
        room_long_name += floor_data["name_long"] + res_room.group(0)
        room_name_plain = room_name_plain.replace(res_room.group(0), "").strip()
        room_short_name = res_room.group(0)
    else:
        room_short_name = ITEM_ROOM_NAME_SHORT_PREFIX + "RMxx"
        room_long_name += ITEM_ROOM_NAME_SHORT_PREFIX + "RMxx"

    return room_short_name, room_long_name, room_name_plain


def get_addresses(project: KNXProject):
    """Extract and process information from a KNX project."""
    group_addresses = project["group_addresses"]
    communication_objects = project["communication_objects"]
    devices = project["devices"]
    group_ranges = project["group_ranges"]

    if not (group_addresses and communication_objects and devices and group_ranges):
        logger.error("One or more essential data structures are empty.")
        raise ValueError("One or more essential data structures are empty.")

    addresses = []
    for address in group_addresses.values():
        if should_ignore_address(address):
            continue

        res_floor = find_floor_in_address(address, group_ranges)
        res_room = RE_ITEM_ROOM.search(address["name"])

        # For debugging
        if address["address"] in ("3/1/4", "3/1/43"):
            logger.debug("create specific address")

        addresses.append(
            {
                "Group name": address["name"],
                "Address": address["address"],
                "Description": address["description"],
                "communication_object": extract_communication_objects(
                    address, communication_objects, devices
                ),
                "Floor": get_short_floor_name(res_floor),
                "Room": res_room.group(0) if res_room else UNKNOWN_ROOM_NAME,
                "DatapointType": format_datapoint_type(address),
            }
        )

    return addresses


def should_ignore_address(address):
    """Determine if an address should be ignored based on various criteria."""
    if (
        "ignore" in address["comment"]
        or not address["communication_object_ids"]
        or not address["dpt"]
    ):
        logger.debug("Ignore: %s", address["name"])
        return True
    return False


def find_floor_in_address(address, group_ranges):
    """Find the floor associated with an address."""
    res_floor = RE_ITEM_FLOOR.search(address["name"])
    if not res_floor:
        address_split = address["address"].split("/")
        gr_top = group_ranges.get(address_split[0])
        gr_middle = gr_top["group_ranges"].get(address_split[0] + "/" + address_split[1])
        res_floor = (
            RE_ITEM_FLOOR.search(gr_middle["name"])
            or RE_ITEM_FLOOR.search(gr_top["name"])
            or RE_FLOOR_NAME_SHORT.search(gr_middle["name"])
            or RE_FLOOR_NAME_SHORT.search(gr_top["name"])
        )
    return res_floor


def extract_communication_objects(address, communication_objects, devices):
    """Extract communication objects for an address."""
    comm_objects = []
    for co_id in address["communication_object_ids"]:
        co = communication_objects[co_id]
        if co["flags"] and (co["flags"]["read"] or co["flags"]["write"]):
            if co.get("device_communication_objects"):
                comm_objects.append(co)
                continue
            device_id = co["device_address"]
            device = devices[device_id]
            if device and device.get("communication_object_ids"):
                matching_device_comms = []
                for device_co_id in device["communication_object_ids"]:
                    device_co = communication_objects.get(device_co_id)
                    if device_co:
                        if device_co.get("channel") and co["channel"] == device_co["channel"]:
                            matching_device_comms.append(device_co)
                        elif device_co.get("text") and co["text"] == device_co["text"]:
                            matching_device_comms.append(device_co)
                co["device_communication_objects"] = matching_device_comms
                # co["device_communication_objects"] = [
                #    communication_objects[device_co_id]
                #    for device_co_id in device['communication_object_ids']
                #    if co['channel'] == communication_objects[device_co_id].get("channel", co['channel'])
                # ]
        comm_objects.append(co)
    return comm_objects


def get_short_floor_name(res_floor):
    """Get short name for a floor."""
    if res_floor:
        floor_name = res_floor.group(0)
        return (
            floor_name
            if floor_name.startswith(ITEM_FLOOR_NAME_SHORT_PREFIX) and len(floor_name) < 6
            else ITEM_FLOOR_NAME_SHORT_PREFIX + floor_name
        )
    return UNKNOWN_FLOOR_NAME


def format_datapoint_type(address):
    """Format datapoint type string."""
    dpt = address["dpt"]
    return f'DPST-{dpt["main"]}-{dpt["sub"]}' if dpt["sub"] else f'DPT-{dpt["main"]}'


def put_addresses_in_building(building, addresses, project: KNXProject):
    """Place addresses in a building object based on their associated floors and rooms."""
    if not (building and addresses and project):
        raise ValueError("One or more input data structures are empty.")

    cabinet_devices = get_distribution_board_devices(project)
    unknown_addresses = []

    for address in addresses:
        # For debugging
        if address["Address"] in ("1/2/25"):
            logger.debug("place specific address")

        if place_address_in_building(building, address, cabinet_devices):
            continue
        read_co = get_sensor_communication_object(address, cabinet_devices)
        if place_address_by_device(building, address, read_co, addresses):
            continue

        # Try to create floor/room dynamically if names exist but not in structure yet
        if create_floor_room_if_missing(building, address):
            continue

        logger.warning("No Room found for %s", address["Group name"])
        unknown_addresses.append(address)
    # TODO: Loop over unknown_addresses to identify Groups/Channels in the same "level"

    # Optional auto-placement for unknown addresses
    if config.get("general", {}).get("auto_place_unknown"):
        auto_place_unknowns(building, unknown_addresses, addresses, cabinet_devices)

    # Always write report for remaining unknowns (for UI/CLI visibility)
    write_unknown_report(unknown_addresses)

    if ADD_MISSING_ITEMS:
        add_unknown_addresses(building, unknown_addresses)
    else:
        logger.info("Unknown addresses: %s", unknown_addresses)
        logger.info("Total unknown addresses: %d", len(unknown_addresses))
    return building


def place_address_in_building(building, address, cabinet_devices):
    """Place a single address in the appropriate location in the building."""
    if (
        address["Floor"]
        and address["Room"]
        and address["Floor"] != UNKNOWN_FLOOR_NAME
        and address["Room"] != UNKNOWN_ROOM_NAME
    ):
        for building_data in building:
            for floor in building_data["floors"]:
                if floor["name_short"] == address["Floor"]:
                    for room in floor["rooms"]:
                        if room["name_short"] == address["Room"]:
                            room.setdefault("Addresses", []).append(address)
                            logger.debug(
                                "Address %s placed in Room: %s, Floor: %s",
                                address["Address"],
                                room["name_short"],
                                floor["name_short"],
                            )
                            return True
    return False


def place_address_by_device(building, address, read_co, addresses):
    """Place address in building based on device association."""
    if read_co:
        for building_data in building:
            for floor in building_data["floors"]:
                for room in floor["rooms"]:
                    if "devices" in room and read_co["device_address"] in room["devices"]:
                        put_address_to_right_place(
                            address, floor["name_short"], room["name_short"], addresses
                        )
                        room["Addresses"].append(address)
                        logger.debug(
                            "Address %s placed in Room (via device association): %s, Floor: %s",
                            address["Address"],
                            room["name_short"],
                            floor["name_short"],
                        )
                        return True
    return False


def put_address_to_right_place(address, floor_name, room_name, addresses):
    """Set floor and room for address and all subaddresses."""
    address["Floor"] = floor_name
    address["Room"] = room_name
    item_subaddress = []
    for co in address.get("communication_object"):
        if co.get("device_communication_objects"):
            for dco in co.get("device_communication_objects"):
                for sub_address in dco.get("group_address_links"):
                    item_subaddress += [
                        item for item in addresses if item.get("Address") == sub_address
                    ]
    if item_subaddress:
        for item in item_subaddress:
            if item["Floor"] != UNKNOWN_FLOOR_NAME and item["Room"] != UNKNOWN_ROOM_NAME:
                continue
            item["Floor"] = floor_name
            item["Room"] = room_name
        logger.debug("here u can put all sub addreses to te right place to")

    return True


# Heuristic: create missing floor/room nodes if names are known but not yet in structure
def create_floor_room_if_missing(building, address):
    """If floor/room names exist (not unknown), create them and place address."""
    floor = address.get("Floor")
    room = address.get("Room")
    if not floor or not room:
        return False
    if floor == UNKNOWN_FLOOR_NAME or room == UNKNOWN_ROOM_NAME:
        return False

    for building_data in building:
        # find or create floor
        target_floor = None
        for fl in building_data.get("floors", []):
            if fl.get("name_short") == floor:
                target_floor = fl
                break
        if target_floor is None:
            target_floor = {
                "Description": floor,
                "Group name": floor,
                "name_long": floor,
                "name_short": floor,
                "rooms": [],
            }
            building_data.setdefault("floors", []).append(target_floor)

        # find or create room
        target_room = None
        for rm in target_floor.get("rooms", []):
            if rm.get("name_short") == room:
                target_room = rm
                break
        if target_room is None:
            target_room = {
                "Description": room,
                "Group name": room,
                "name_long": room,
                "name_short": room,
                "Addresses": [],
            }
            target_floor.setdefault("rooms", []).append(target_room)

        target_room.setdefault("Addresses", []).append(address)
        logger.debug(
            "Created floor/room on-the-fly and placed %s in %s/%s",
            address.get("Address"),
            floor,
            room,
        )
        return True

    return False


def auto_place_unknowns(building, unknown_addresses, all_addresses, cabinet_devices):
    """Heuristisch unbekannte Adressen zuordnen (opt-in per config.general.auto_place_unknown)."""
    placed = 0
    report = []
    floor_pref = config.get("general", {}).get("item_Floor_nameshort_prefix", "=")
    room_pref = config.get("general", {}).get("item_Room_nameshort_prefix", "+")

    def try_assign(addr, floor, room, reason):
        nonlocal placed
        if not floor or not room:
            return False
        if floor == UNKNOWN_FLOOR_NAME or room == UNKNOWN_ROOM_NAME:
            return False
        addr["Floor"] = floor
        addr["Room"] = room
        placed += 1
        report.append(
            {"Address": addr.get("Address"), "Floor": floor, "Room": room, "reason": reason}
        )
        try:
            unknown_addresses.remove(addr)
        except ValueError:
            pass
        # Auch Subadressen übernehmen
        put_address_to_right_place(addr, floor, room, all_addresses)
        return True

    # 1) Device-basierte Vererbung: gleiche device_address wie bekannte Adresse
    for addr in list(unknown_addresses):
        device_ids = set()
        for co in addr.get("communication_object", []):
            dev = co.get("device_address")
            if dev and dev not in cabinet_devices:
                device_ids.add(dev)
        if not device_ids:
            continue
        candidates = set()
        for other in all_addresses:
            if other is addr:
                continue
            if other.get("Floor") in (UNKNOWN_FLOOR_NAME, None) or other.get("Room") in (
                UNKNOWN_ROOM_NAME,
                None,
            ):
                continue
            for co in other.get("communication_object", []):
                if co.get("device_address") in device_ids:
                    candidates.add((other["Floor"], other["Room"]))
        if len(candidates) == 1:
            floor, room = next(iter(candidates))
            try_assign(addr, floor, room, "device-match")

    # 2) Namensheuristik aus Group name ("=Floor +Room ...")
    import re

    floor_rx = re.compile(r"%s([A-Za-z0-9\.]+)" % re.escape(floor_pref))
    room_rx = re.compile(r"%s([A-Za-z0-9_\-\.]+)" % re.escape(room_pref))
    for addr in list(unknown_addresses):
        gname = addr.get("Group name", "")
        floor = room = None
        m_f = floor_rx.search(gname)
        m_r = room_rx.search(gname)
        if m_f:
            floor = m_f.group(1)
            if not floor.startswith(floor_pref):
                floor = floor_pref + floor
        if m_r:
            room = m_r.group(1)
            if not room.startswith(room_pref):
                room = room_pref + room
        if floor and room:
            try_assign(addr, floor, room, "name-heuristic")

    if report:
        logger.info("auto_place_unknown: placed=%d details=%s", placed, report)
    else:
        logger.info("auto_place_unknown: nothing placed")


def write_unknown_report(unknown_addresses):
    """Write report for remaining unknown addresses."""
    if not unknown_addresses:
        return
    try:
        import json
        from pathlib import Path

        report = {
            "total": len(unknown_addresses),
            "addresses": [
                {
                    "Address": a.get("Address"),
                    "Group name": a.get("Group name"),
                    "DPT": a.get("dpt"),
                    "Floor": a.get("Floor"),
                    "Room": a.get("Room"),
                }
                for a in unknown_addresses
            ],
        }
        base = config.get("openhab_path", "openhab")
        Path(base).mkdir(parents=True, exist_ok=True)
        Path(base, "unknown_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Failed to write unknown_report.json: %s", e)


def add_unknown_addresses(building, unknown_addresses):
    """Add unknown addresses to a default floor and room in the building."""
    default_floor = {
        "Description": UNKNOWN_FLOOR_NAME,
        "Group name": UNKNOWN_FLOOR_NAME,
        "name_long": UNKNOWN_FLOOR_NAME,
        "name_short": UNKNOWN_FLOOR_NAME,
        "rooms": [
            {
                "Description": UNKNOWN_ROOM_NAME,
                "Group name": UNKNOWN_ROOM_NAME,
                "name_long": UNKNOWN_ROOM_NAME,
                "name_short": UNKNOWN_ROOM_NAME,
                "Addresses": unknown_addresses,
            }
        ],
    }
    building[0]["floors"].append(default_floor)
    logger.info(
        "Added default Floor and Room for unknown addresses: %s, %s",
        UNKNOWN_FLOOR_NAME,
        UNKNOWN_ROOM_NAME,
    )


def get_sensor_communication_object(address, cabinet_devices):
    """Search for a sensor communication object enabled for reading or transmitting."""
    for co in address.get("communication_object", []):
        if co["device_address"] in cabinet_devices:
            continue
        if co["flags"].get("read") or co["flags"].get("transmit"):
            logger.debug("Found sensor communication object: %s", co["name"])
            return co
    logger.debug("No sensor communication object found.")
    return None


def create_json_dump(project: KNXProject, file_path: Path):
    """Create a JSON dump from a KNX project file."""
    with open(f"tests/{file_path.name}.json", "w", encoding="utf8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)


def get_gateway_ip(project: KNXProject):
    """Get the IP address of the gateway device."""
    devices = project["devices"]
    if not devices:
        logger.error("'devices' is empty.")
        raise ValueError("'devices' is empty.")

    for device in devices.values():
        if device["hardware_name"].strip() in config["devices"]["gateway"]["hardware_name"]:
            description = device["description"].strip()
            ip_match = re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", description)
            if ip_match:
                return ip_match.group()
    return None


def get_distribution_board_devices(project: KNXProject):
    """Get a list of devices in distribution boards."""
    locations = project["locations"]
    return get_recursive_spaces(locations)


def get_recursive_spaces(spaces):
    """Recursively get spaces in a location."""
    devices = []
    for space in spaces.values():
        if space["type"] == "DistributionBoard":
            devices.extend(space["devices"])
        if "spaces" in space:
            devices.extend(get_recursive_spaces(space["spaces"]))
    return devices


def is_homekit_enabled(project: KNXProject):
    """Determine if HomeKit is enabled for the project."""
    # TODO: Read project info or some other method to get Homekit enabled status
    comment_value = project["info"].get("comment")
    if isinstance(comment_value, str) and comment_value:
        comments = comment_value.casefold().split(";")
        for comment in comments:
            if comment.startswith("homekit="):
                return str2bool(comment.replace("homekit=", ""))
            elif "homekit" in comment:
                return True
    return False


def is_alexa_enabled(project: KNXProject):
    """Determine if Alexa is enabled for the project."""
    comment_value = project["info"].get("comment")
    if isinstance(comment_value, str) and comment_value:
        comments = comment_value.casefold().split(";")
        for comment in comments:
            if comment.startswith("alexa="):
                return str2bool(comment.replace("alexa=", ""))
            elif "alexa" in comment:
                return True
    return False


def str2bool(v):
    """Convert a string to a boolean value.

    Returns True for 'yes', 'true', 't', '1' (case-insensitive), otherwise False.
    """
    return normalize_string(v) in ("yes", "true", "t", "1")


def main():
    """Main function"""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Reads KNX project file and creates an OpenHAB output for things/items/sitemap"
    )
    parser.add_argument("--file_path", type=Path, help="Path to the input KNX project.")
    parser.add_argument("--knxPW", type=str, help="Password for KNX project file if protected")
    parser.add_argument("--readDump", action="store_true", help="Read KNX project from JSON dump")
    args = parser.parse_args()

    if not args.file_path:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", 1)
            file_path = filedialog.askopenfilename()
            if not file_path:
                raise SystemExit
            args.file_path = Path(file_path)
            if args.file_path.suffix == ".json":
                args.readDump = True
        except Exception:
            # Headless or tkinter not available: bail with a helpful message
            raise SystemExit(
                "No --file_path provided and tkinter GUI unavailable. "
                "Run with --file_path <path> or install python3-tk."
            )

    if args.readDump:
        with open(args.file_path, encoding="utf-8") as f:
            project = json.load(f)
    else:
        knxproj = XKNXProj(path=args.file_path, password=args.knxPW, language="de-DE")
        project = knxproj.parse()
        create_json_dump(project, args.file_path)

    building = create_building(project)
    addresses = get_addresses(project)
    house = put_addresses_in_building(building, addresses, project)
    prj_name = house[0]["name_long"]
    ip = get_gateway_ip(project)
    homekit_enabled = is_homekit_enabled(project)
    alexa_enabled = is_alexa_enabled(project)

    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = ip
    ets_to_openhab.B_HOMEKIT = homekit_enabled
    ets_to_openhab.B_ALEXA = alexa_enabled
    if prj_name:
        ets_to_openhab.PRJ_NAME = prj_name

    logger.info("Calling ets_to_openhab.main()")
    ets_to_openhab.main()


if __name__ == "__main__":
    main()
