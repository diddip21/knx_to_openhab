import knxproject_to_openhab as k2o
from config import config


def _make_building(floor_short, room_short):
    return [
        {
            "floors": [
                {
                    "name_short": floor_short,
                    "rooms": [
                        {
                            "name_short": room_short,
                            "Addresses": [],
                            "devices": ["1.1.1"],
                        }
                    ],
                }
            ]
        }
    ]


def test_auto_place_unknowns_device_match():
    building = _make_building("=EG", "+RM1")

    known = {
        "Group name": "=EG +RM1 Licht",
        "Address": "1/1/1",
        "Floor": "=EG",
        "Room": "+RM1",
        "communication_object": [{"device_address": "1.1.1"}],
    }
    unknown = {
        "Group name": "Unbekannt Licht",
        "Address": "1/1/2",
        "Floor": k2o.UNKNOWN_FLOOR_NAME,
        "Room": k2o.UNKNOWN_ROOM_NAME,
        "communication_object": [{"device_address": "1.1.1"}],
    }

    unknowns = [unknown]
    all_addresses = [known, unknown]

    k2o.auto_place_unknowns(building, unknowns, all_addresses, cabinet_devices=set())

    assert unknown["Floor"] == "=EG"
    assert unknown["Room"] == "+RM1"
    assert unknowns == []


def test_auto_place_unknowns_name_heuristic():
    config["general"]["item_Floor_nameshort_prefix"] = "="
    config["general"]["item_Room_nameshort_prefix"] = "+"

    building = _make_building("=EG", "+RM1")
    unknown = {
        "Group name": "=OG +RM2 Steckdose",
        "Address": "2/1/1",
        "Floor": k2o.UNKNOWN_FLOOR_NAME,
        "Room": k2o.UNKNOWN_ROOM_NAME,
        "communication_object": [],
    }

    unknowns = [unknown]
    all_addresses = [unknown]

    k2o.auto_place_unknowns(building, unknowns, all_addresses, cabinet_devices=set())

    assert unknown["Floor"] == "=OG"
    assert unknown["Room"] == "+RM2"
    assert unknowns == []
