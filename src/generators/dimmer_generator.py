"""Generator for Dimmer devices"""
import logging
from typing import Dict, Optional
from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class DimmerGenerator(BaseDeviceGenerator):
    """Generator for dimmer/light devices with brightness control"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a dimmer device"""
        return address['DatapointType'] == get_datapoint_type('dimmer')
    
    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration for dimmer.
        
        Context should contain:
        - floor_nr: Floor numbe
        - room_nr: Room number
        - floor_name: Floor name
        - room_name: Room name
        - item_name: Pre-generated item name
        """
        # Create default context if not provided
        if context is None:
            context = {}
                        
        # Create result
        result = DeviceGeneratorResult()
        
        # Get configuration
        define = self.config.get('defines', {}).get('dimmer', {})
        if not define:
            logger.warning(f"No dimmer definition found in config")
            return result
        
        # Extract base information
        basename = address.get('Group_name', 'Dimmer')
        item_name = context.get('item_name', basename.replace(' ', '_'))
        
        # Set result properties
        result.item_type = 'Dimmer'
        result.label = f"{basename}"
        result.item_name = item_name
        result.icon = define.get('icon', 'light')
                result.item_icon = define.get('icon', 'light')
        result.equipment = 'Lightbulb'
        result.semantic_info = '["Light"]'
        
        # Find status address for thing_info
        status_address = self.find_related_address(
            address.get('communication_object', [{}])[0] if address.get('communication_object') else {},
            'status_suffix',
            define
        )
        
        # Build thing_info string
        main_addr = address.get('Address', '')
        if status_address:
            status_addr = status_address.get('Address', '')
            result.thing_info = f'position="{main_addr}" state="{status_addr}"'
        else:
            # No status address found - return None as test expects
            result.success = False
            return None
        
        # Mark as successful
        result.success = True
        result.used_addresses.append(address.get('Address', ''))

                # Add homekit metadata if enabled
        if self.config.get('homekit_enabled', False):
            result.metadata['homekit'] = 'Lighting'
        
        return result
