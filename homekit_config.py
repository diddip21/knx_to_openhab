"""Dependency-free validation shared by the generator and configuration API."""

from collections.abc import Mapping

HOMEKIT_BRIDGE_COUNT = "homekit_bridge_count"


def bridge_count(general: Mapping) -> int:
    """Require an explicit positive JSON integer; old configurations use bridge 1."""
    value = general.get(HOMEKIT_BRIDGE_COUNT, 1)
    if type(value) is not int or value < 1:
        raise ValueError("general.homekit_bridge_count must be a positive integer")
    return value
