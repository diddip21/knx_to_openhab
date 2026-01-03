"""Generator for Scene devices"""
import logging
from typing import Dict, Optional

from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult

logger = logging.getLogger(__name__)


class SceneGenerator(BaseDeviceGenerator):
    """Generator for scene/button devices with scene triggering"""

    def can_handle(self, address: Dict) -> bool:
        """Check if address is a scene device"""
        return address['DatapointType'] == 'DPST-18-1'  # Scene Control

    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration for scene.

        Context should contain:
            - floor_nr: Floor number
            - room_nr: Room number
            - floor_name: Floor name
            - room_name: Room name
            - item_name: Pre-generated item name

        Args:
            address: KNX address dictionary
            context: Context dictionary with floor/room information

        Returns:
            DeviceGeneratorResult with items, things and thing_info
        """
        # Create default context if not provided
        if context is None:
            context = {
                'item_name': address.get('Group_name', '').replace(' ', '_'),
                'floor_nr': 0,
                'room_nr': 0,
                        'floor_name': address.get('Floor_name', 'Unknown'),
                'room_name': address.get('Room_name', 'Unknown')
            }

        result = DeviceGeneratorResult()

        # Get configuration
        define = self.config.get('defines', {}).get('scene', {})

        # Extract base information
        basename = address.get('Group_name') or address.get('Group name', 'Scene')
        item_name = context.get('item_name', basename.replace(' ', '_'))

        # Set result properties
        result.item_type = 'Number'
        result.label = f"{basename}"
        result.item_name = item_name
        result.icon = define.get('icon', 'scene')
        result.item_icon = define.get('icon', 'scene')
        result.success = True
        
        main_addr = address.get('Address', '')
        result.used_addresses.append(main_addr)

        # Scene triggering
        result.thing_info = {
            'control': main_addr.replace('/', ':')
        }

        return result

    def _get_channel_name(self, address: Dict, channel_type: str) -> str:
        """Generate channel name from address and type"""
        knx_address = address.get('Address', '').replace('/', '_')
        return f"{knx_address}_{channel_type}"
    
    def _format_ga(self, address: str) -> str:
        """Format group address for OpenHAB"""
        return address.replace('/', ':')
    
    def _add_to_groups(self, result, context: Dict, define: Dict):
        """Add item to appropriate groups based on context"""
        # This method can be extended based on your grouping logic
        pass
