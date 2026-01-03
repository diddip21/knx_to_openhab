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
        floor_name = floor.get('Group name', f'Floor {floor_nr}')
        if self.config.get('general', {}).get('FloorNameFromDescription') and floor.get('Description'):
            floor_name = floor['Description']
        
        items = f"Group   map{floor_nr}   \"{floor_name}\" (Base) [\"Location\"]\n"
        items += f"Group:Rollershutter:AVG        map{floor_nr}_Blinds         \"{floor_name} Jalousie/Rollo\"      <rollershutter>    (map{floor_nr})  [\"Blinds\"]\n"
        items += f"Group:Switch:OR(ON, OFF)       map{floor_nr}_Lights         \"{floor_name} Beleuchtung\"         <light>            (map{floor_nr})  [\"Light\"]\n"
        items += f"Group:Contact:OR(OPEN, CLOSED) map{floor_nr}_Contacts       \"{floor_name} Öffnungsmelder\"      <contact>          (map{floor_nr})  [\"OpenState\"]\n"
        items += f"Group:Number:Temperature:AVG   map{floor_nr}_Temperature    \"{floor_name} Ø Temperatur\"        <temperature>      (map{floor_nr})  [\"Measurement\", \"Temperature\"]\n"
        
        sitemap = f"Frame label=\"{floor_name}\" {{\n"
        
        return items, sitemap
    
    def _generate_room(self, room: Dict, floor: Dict, floor_nr: int, room_nr: int) -> Tuple[str, str, str]:
        """Generate room-level configuration."""
        room_name = room.get('Group name', f'Room {room_nr}')
        if self.config.get('general', {}).get('RoomNameFromDescription') and room.get('Description'):
            room_name = room['Description']
        
        items = f"Group   map{floor_nr}_{room_nr}   \"{room_name}\"  (map{floor_nr})   [\"Room\", \"{room_name}\"]\n"
        things = ''
        sitemap = f"     Group item=map{floor_nr}_{room_nr} label=\"{room_name}\" "
        group = ""
        
        addresses = room.get('Addresses', [])
        logger.debug(f"Processing room: {room_name} with {len(addresses)} addresses")
        
        # Process each address
        for address in addresses:
            if self._is_address_used(address['Address']):
                continue
            
            if 'ignore' in address.get('Description', '').lower():
                continue
            
            # Try each generator
            for generator in self.generators:
                if generator.can_handle(address):
                    result = self._process_address(
                        address, generator, floor, room, floor_nr, room_nr
                    )
                    if result:
                        items += result['item']
                        things += result['thing']
                        group += result['sitemap']
                        break
        
        if group:
            sitemap += f" {{\n{group}\n    }}\n"
        else:
            sitemap += "\n "
        
        return items, things, sitemap
    
    def _process_address(self, address: Dict, generator: BaseDeviceGenerator,
                        floor: Dict, room: Dict, floor_nr: int, room_nr: int) -> Dict:
        """Process single address with generator."""
        # Find communication object
        co = None
        if 'communication_object' in address and address['communication_object']:
            co = address['communication_object'][0]  # Use first CO
        
        # Generate configuration
        gen_result = generator.generate(address, co)
        if not gen_result:
            return None
        
        # Mark address as used
        self._mark_used(address['Address'])
        
        # Build item name
        item_name = self._build_item_name(address, floor, room)
        
        # Build full configuration
        return self._build_full_config(
            item_name, address, gen_result, floor_nr, room_nr
        )
    
    def _build_item_name(self, address: Dict, floor: Dict, room: Dict) -> str:
        """Build OpenHAB item name."""
        floor_short = floor.get('name_short', '')
        room_short = room.get('name_short', '')
        
        name = address['Group name']
        # Remove floor and room names
        name = name.replace(floor.get('Group name', ''), '')
        name = name.replace(room.get('Group name', ''), '')
        name = ' '.join(name.split())  # Clean whitespace
        
        item_name = f"i_{floor_short}_{room_short}_{name}"
        # Clean special characters
        item_name = re.sub(r'[^A-Za-z0-9_]+', '_', item_name)
        item_name = re.sub(r'_+', '_', item_name)
        
        return item_name
    
    def _build_full_config(self, item_name: str, address: Dict, gen_result: Dict,
                          floor_nr: int, room_nr: int) -> Dict:
        """Build complete item/thing/sitemap configuration."""
        # Thing
        thing_type = gen_result['item_type'].lower().split(":")[0]
        thing_info = gen_result['thing_info']
        if isinstance(thing_info, dict):
            thing_info = ', '.join([f'{k}="{v}"' for k, v in thing_info.items()])
            
        thing = f"Type {thing_type}    :   {item_name}   \"{address['Group name']}\"   [ {thing_info} ]\n"
        
        # Item groups
        root_group = f"map{floor_nr}_{room_nr}"
        
        # Handle equipment grouping
        equipment = gen_result.get('equipment', '')
        if equipment:
            root_group = self._handle_equipment(item_name, address, gen_result, root_group)
        
        # Homekit instance management
        metadata = gen_result.get('metadata', '')
        if 'homekit=' in metadata:
            metadata = self._add_homekit_instance(metadata)
        
        # Build item
        icon = gen_result['item_icon']
        if icon and not icon.startswith('<'):
            icon = f"<{icon}>"
        
        item_label = address['Group name']  # Simplified - should apply name cleaning
        item = f"{gen_result['item_type']}   {item_name}   \"{item_label}\"   {icon}   ({root_group})   {gen_result['semantic_info']}    {{ channel=\"knx:device:bridge:generic:{item_name}\" {metadata} }}\n"
        
        # Sitemap
        sitemap_type = 'Default'
        sitemap = f"        {sitemap_type} item={item_name} label=\"{item_label}\"\n"
        
        # Track influx export
        if 'influx' in address.get('Description', ''):
            self.export_to_influx.append(item_name)
        
        return {
            'item': item,
            'thing': thing,
            'sitemap': sitemap
        }
    
    def _handle_equipment(self, item_name: str, address: Dict, gen_result: Dict, root_group: str) -> str:
        """Handle equipment grouping."""
        equipment = gen_result['equipment']
        label = address['Group name']  # Simplified
        
        if label not in self.equipments:
            self.equipments[label] = item_name
            # Create equipment group (would need to be added to items)
        
        return f"equipment_{self.equipments[label]}"
    
    def _add_homekit_instance(self, metadata: str) -> str:
        """Add homekit instance and manage accessory count."""
        if ']' in metadata:
            metadata = metadata.replace(']', f", Instance={self.homekit_instance}]")
        else:
            metadata += f" [Instance={self.homekit_instance}]"
        
        self.homekit_accessory_count += 1
        if self.homekit_accessory_count >= self.homekit_max_per_instance:
            self.homekit_accessory_count = 0
            self.homekit_instance += 1
        
        return metadata
    
    def _is_address_used(self, address: str) -> bool:
        """Check if address is already used."""
        return address in self.used_addresses
    
    def _mark_used(self, address: str):
        """Mark address as used."""
        if address not in self.used_addresses:
            self.used_addresses.append(address)
