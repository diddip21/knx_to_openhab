"""Main orchestrator for building generation"""

import logging
import re
from typing import List, Dict, Tuple

from .generators.base_generator import BaseDeviceGenerator
from .generators.dimmer_generator import DimmerGenerator
from .generators.rollershutter_generator import RollershutterGenerator
from .generators.switch_generator import SwitchGenerator
from .generators.heating_generator import HeatingGenerator
from .generators.generic_generator import GenericGenerator
from .utils.address_cache import AddressCache
from config import config

logger = logging.getLogger(__name__)


class BuildingGenerator:
    """Main generator that orchestrates all device generators"""

    def __init__(self, configuration: Dict, all_addresses: List[Dict]):
        """
        Initialize building generator.

        Args:
            configuration: Configuration dictionary
            all_addresses: List of all KNX addresses
        """
        self.config = configuration
        self.all_addresses = all_addresses
        self.cache = AddressCache()
        self.cache.build_index(all_addresses)

        # Initialize generators in priority order
        self.generators = [
            DimmerGenerator(configuration, all_addresses),
            RollershutterGenerator(configuration, all_addresses),
            HeatingGenerator(configuration, all_addresses),
            SwitchGenerator(configuration, all_addresses),
            GenericGenerator(configuration, all_addresses),  # Fallback
        ]

        # Tracking
        self.used_addresses = []
        self.equipments = {}
        self.export_to_influx = []
        self.window_contacts = []

        # Homekit tracking
        self.homekit_instance = 1
        self.homekit_accessory_count = 0
        self.homekit_max_per_instance = 130

    def generate(self, floors: List[Dict]) -> Tuple[str, str, str]:
        """
        Generate complete OpenHAB configuration.

        Args:
            floors: List of floor dictionaries with rooms and addresses

        Returns:
            Tuple of (items, sitemap, things) strings
        """
        items = ''
        sitemap = ''
        things = ''

        logger.info(f"Starting building generation with {len(floors)} floors")

        floor_nr = 0
        for floor in floors:
            floor_nr += 1
            floor_items, floor_sitemap = self._generate_floor(floor, floor_nr)
            items += floor_items
            sitemap += floor_sitemap

            room_nr = 0
            for room in floor.get('rooms', []):
                room_nr += 1
                room_items, room_things, room_sitemap = self._generate_room(
                    room, floor, floor_nr, room_nr
                )
                items += room_items
                things += room_things
                sitemap += room_sitemap

        sitemap += "}\n "

        logger.info(f"Generation complete. Cache stats: {self.cache.get_statistics()}")

        return items, sitemap, things

    def _generate_floor(self, floor: Dict, floor_nr: int) -> Tuple[str, str]:
        """Generate floor-level configuration."""
        floor_name = floor.get('Group_name', f'Floor {floor_nr}')
        if self.config.get('general', {}).get('FloorNameFromDescription') and floor.get('Description'):
            floor_name = floor['Description']

        items = f"Group   __map[{floor_nr}]   \"{floor_name}\" (Base) [\"Location\"] \n"
        items += f"Group:Rollershutter:AVG      __map[{floor_nr}]_Blinds            \"{floor_name} Jalousie/Rollo\"     <rollershutter>    (map[{floor_nr}])  [\"Blind
