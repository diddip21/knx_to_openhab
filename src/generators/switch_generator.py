"""Generator for switch devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class SwitchGenerator(BaseDeviceGenerator):
    """Generator for KNX switch devices"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a switch."""
        return address['DatapointType'] == get_datapoint_type('switch')
    
    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration for a switch.
        
        Returns:
            DeviceGeneratorResult with generated configuration
        """
        if context is None:
            context = {}

        result = DeviceGeneratorResult()
        define = self.config.get('defines', {}).get('switch', {})        
        if not define:
            logger.warning(f"No switch definition found in config")
            return result
            
        # Extract base information
        basename = address.get('Group_name') or address.get('Group name', 'Switch')
        item_name = context.get('item_name', basename.replace(' ', '_'))
        
        # Set result properties
        result.item_type = 'Switch'
        result.label = f"{basename}"
        result.item_name = item_name
        result.icon = define.get('icon', 'switch')
        result.item_icon = define.get('icon', 'switch')
        result.equipment = 'Switch'
        result.semantic_info = '["Switch"]'
        
        # Find communication object if not provided in context (though context usually doesn't have it)
        co = address.get('communication_object', [{}])[0] if address.get('communication_object') else {}
        
        # Find status address
        status_address = self.find_related_address(
            co,
            'status_suffix',
            define,
            base_address_str=address.get('Address')
        )
        
        main_addr = address.get('Address', '')
        if status_address:
            status_addr = status_address.get('Address', '')
            result.thing_info = f'ga="{main_addr}+<{status_addr}"'
            result.used_addresses.append(status_addr)
        else:
            result.thing_info = f'ga="{main_addr}"'
        
        result.used_addresses.append(main_addr)

        # Apply metadata changes based on name patterns
        if 'change_metadata' in define:
            for pattern, metadata_changes in define['change_metadata'].items():
                if pattern in basename:
                    for key, value in metadata_changes.items():
                        if key == 'equipment':
                            result.equipment = value
                        elif key == 'item_icon':
                            result.item_icon = value
                        elif key == 'semantic_info':
                            result.semantic_info = value
                        elif key == 'homekit' and self.config.get('homekit_enabled', False):
                            result.metadata['homekit'] = value
                        elif key == 'alexa' and self.config.get('alexa_enabled', False):
                            result.metadata['alexa'] = value
                    break
        
        # Default Homekit/Alexa if no pattern matched
        if not result.metadata:
            if self.config.get('homekit_enabled', False):
                result.metadata['homekit'] = 'Switchable'
            if self.config.get('alexa_enabled', False):
                result.metadata['alexa'] = 'Switch'
        
        result.success = True
        return result
