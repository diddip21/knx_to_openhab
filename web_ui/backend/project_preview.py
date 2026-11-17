"""Build the passphrase-free structure preview shown for a KNX project."""


def get_general_config(knx_module):
    """Return the generator's ``general`` settings from the module's config dict.

    Returns ``None`` when the loaded generator module predates the override or
    carries no config mapping, so callers keep the plain ETS detection.
    """
    config_dict = getattr(knx_module, "config", None)
    if isinstance(config_dict, dict):
        return config_dict.get("general")
    return None


def resolve_homekit_enabled(knx_module, project, general_config=None):
    """Return the effective HomeKit value for a project.

    Prefers the generator's tri-state override resolution; falls back to the
    plain ETS detection when the loaded generator module predates the override.
    """
    resolver = getattr(knx_module, "resolve_homekit_mode", None)
    if resolver is None:
        return knx_module.is_homekit_enabled(project)
    return resolver(project, general_config)


def build_project_preview(project, knx_module, parsed=None, general_config=None):
    """Return the UI preview payload for a parsed KNX project.

    ``parsed`` may contain the building, addresses, and house already prepared
    by the generator so the job worker does not repeat the parsing work.
    ``general_config`` carries the generator's ``general`` settings so the
    reported HomeKit value reflects the configured override.
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
            "homekit_enabled": resolve_homekit_enabled(knx_module, project, general_config),
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
