"""Generator for rollershutter/blind devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class RollershutterGenerator(BaseDeviceGenerator):
    """Generator for KNX rollershutter/blind devices"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a rollershutter."""
        return address['DatapointType'] == get_datapoint_type('rollershutter')
    
    def generate(self, address: Dict, context: Optional[Dict] = None) -> Optional[DeviceGeneratorResult]:
        """
        Generate OpenHAB configuration for a rollershutter.
        
        Returns:
            DeviceGeneratorResult with generated configuration
        """
        if context is None:
            context = {}

        result = DeviceGeneratorResult()
        define = self.config.get('defines', {}).get('rollershutter', {})        
        if not define:
            logger.warning(f"No rollershutter definition found in config")
            return result

        basename = address.get('Group_name') or address.get('Group name', 'RollerShutter')
        item_name = context.get('item_name', basename.replace(' ', '_'))
        
        result.item_type = 'Rollershutter'
        result.label = basename
        result.item_name = item_name
        result.icon = define.get('icon', 'rollershutter')
        result.item_icon = define.get('icon', 'rollershutter')
        
        # Find communication object
        co = address.get('communication_object', [{}])[0] if address.get('communication_object') else {}
        
        main_addr = address.get('Address', '')
        result.used_addresses.append(main_addr)

        # Find related addresses
        stop_address = self.find_related_address(co, 'stop_suffix', define, base_address_str=main_addr)
        position_address = self.find_related_address(co, 'position_suffix', define, base_address_str=main_addr)
        
        # Build thing_info string
        thing_parts = [f'upDown="{main_addr}"']
        
        if stop_address:
            stop_addr = stop_address.get('Address', '')
            thing_parts.append(f'stopMove="{stop_addr}"')
            result.used_addresses.append(stop_addr)
            
        if position_address:
            pos_addr = position_address.get('Address', '')
            thing_parts.append(f'position="{pos_addr}"')
            result.used_addresses.append(pos_addr)
            
        result.thing_info = " ".join(thing_parts)
        
        # Incomplete check (test_generate_incomplete_rollershutter expects this)
        if not stop_address and not position_address and not (co and co.get('device_communication_objects')):
            result.success = False
            # We still return the result object for integration tests
        else:
            result.success = True
            
        return result
