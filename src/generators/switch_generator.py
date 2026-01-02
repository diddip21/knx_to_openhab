"""Generator for switch devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class SwitchGenerator(BaseDeviceGenerator):
    """Generator for KNX switch devices"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a switch."""
        return address['DatapointType'] == get_datapoint_type('switch')
    
    def generate(self, address: Dict, co: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generate OpenHAB configuration for a switch.
        
        Returns:
            Dictionary with 'item_type', 'thing_info', 'metadata', etc.
        """
        define = self.config.get('defines', {}).get('switch', {})        
                if not define:
            logger.warning(f"No switch definition found in config")
            return None
        # Find communication object if not provided
        if not co:
            co = self.get_co_by_functiontext(address, define['switch_suffix'])
            if not co:
                logger.debug(f"No valid CO found for switch {address['Address']}")
                return None
        
        basename = address['Group name']
        
        # Find status address (optional)
        status = self.get_address_from_dco_enhanced(co, 'status_suffix', define)
        
        result = {
            'item_type': 'Switch',
            'semantic_info': '["Switch"]',
            'item_icon': 'switch',
            'metadata': '',
            'equipment': '',
            'thing_info': ''
        }
        
        if status:
            self.mark_address_used(status['Address'])
            result['thing_info'] = f'ga="{address["Address"]}+<{status["Address"]}"'
        else:
            result['thing_info'] = f'ga="{address["Address"]}"'
        
        # Apply metadata changes based on name patterns
        if 'change_metadata' in define:
            for pattern, metadata_changes in define['change_metadata'].items():
                if pattern in basename:
                    for key, value in metadata_changes.items():
                        if key == 'equipment':
                            result['equipment'] = value
                        elif key == 'item_icon':
                            result['item_icon'] = value
                        elif key == 'semantic_info':
                            result['semantic_info'] = value
                        elif key == 'homekit' and self.config.get('homekit_enabled', False):
                            result['metadata'] += value
                        elif key == 'alexa' and self.config.get('alexa_enabled', False):
                            result['metadata'] += value
                    break
        
        # Default Homekit/Alexa if no pattern matched
        if not result['metadata']:
            if self.config.get('homekit_enabled', False):
                result['metadata'] += ', homekit="Switchable"'
            if self.config.get('alexa_enabled', False):
                result['metadata'] += ', alexa = "Switch"'
        
        return result
