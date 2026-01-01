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

    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:        """
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
        if context is None:            context = {
                'item_name': address.get('Group_name', '').replace(' ', '_'),
                'floor_nr': 0,
                'room_nr': 0,
                'floor_name': address.get('Floor_name', 'Unknown'),
                'room_name': address.get('Room_name', 'Unknown')
            }

        result = DeviceGeneratorResult()

        # Get configuration
        define = self.config['defines']['scene']

        # Extract base information
        basename = address['Group_name']
        item_name = context.get('item_name', basename.replace(' ', '_'))

        # Scene devices are typically buttons/triggers
        result.item_type = 'Number'
        result.label = f"{basename}"
        result.item_name = item_name

        # Add icon
        result.icon = define.get('icon', 'scene')

        # Add channel
        result.channel_id = self._get_channel_name(address, 'trigger')

        # Scene triggering
        result.thing_info = {
            'control': self._format_ga(address.get('Address', ''))
        }

        # Add to groups
        self._add_to_groups(result, context, define)

        return result
