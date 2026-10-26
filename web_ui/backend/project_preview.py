"""Build the passphrase-free structure preview shown for a KNX project."""


def build_project_preview(project, knx_module, parsed=None):
    """Return the UI preview payload for a parsed KNX project.

    ``parsed`` may contain the building, addresses, and house already prepared
    by the generator so the job worker does not repeat the parsing work.
    """
    if parsed is None:
        building = knx_module.create_building(project)
        addresses = knx_module.get_addresses(project)
        house = knx_module.put_addresses_in_building(building, addresses, project)
    else:
        building, addresses, house = parsed

    project_name = house[0].get("name_long") if house else None
    unknown_items = []
    for address in addresses:
        floor_name = address.get("Floor", "").strip()
        room_name = address.get("Room", "").strip()
        if (
            not floor_name
            or floor_name.upper() in ("UNKNOWN", "UNBEKANNT")
            or not room_name
            or room_name.upper() in ("UNKNOWN", "UNBEKANNT")
        ):
            unknown_items.append(
                {
                    "name": address.get("Group name", "Unknown Address"),
                    "address": address.get("Address", "N/A"),
                    "floor": floor_name or "None",
                    "room": room_name or "None",
                }
            )

    preview = {
        "metadata": {
            "project_name": project_name,
            "gateway_ip": knx_module.get_gateway_ip(project),
            "homekit_enabled": knx_module.is_homekit_enabled(project),
            "alexa_enabled": knx_module.is_alexa_enabled(project),
            "total_addresses": len(addresses),
            "unknown_items": unknown_items,
        },
        "buildings": [],
    }

    for building_data in house or []:
        building_info = {
            "name": building_data.get(
                "Description", building_data.get("Group name", "Unknown Building")
            ),
            "description": building_data.get("name_long", ""),
            "floors": [],
        }
        for floor_data in building_data.get("floors", []):
            floor_info = {
                "name": floor_data.get(
                    "Description", floor_data.get("Group name", "Unknown Floor")
                ),
                "description": floor_data.get("name_long", ""),
                "rooms": [],
            }
            for room_data in floor_data.get("rooms", []):
                formatted_addresses = [
                    {
                        "Group name": address.get(
                            "Group name", address.get("name", "Unknown Address")
                        ),
                        "Address": address.get("Address", address.get("address", "N/A")),
                    }
                    for address in room_data.get("Addresses", [])
                ]
                floor_info["rooms"].append(
                    {
                        "name": room_data.get(
                            "Description", room_data.get("Group name", "Unknown Room")
                        ),
                        "description": room_data.get("name_long", ""),
                        "address_count": len(formatted_addresses),
                        "device_count": len(room_data.get("devices", [])),
                        "addresses": formatted_addresses,
                    }
                )
            building_info["floors"].append(floor_info)
        preview["buildings"].append(building_info)

    return preview
