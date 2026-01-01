"""Generic generator for devices using datapoint_mappings"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator

logger = logging.getLogger(__name__)


class GenericGenerator(BaseDeviceGenerator):
    """Generic generator for devices defined in datapoint_mappings config"""
    
    def __init__(self, config: Dict, all_addresses: list):
        super().__init__(config, all_addresses)
        self.datapoint_mappings = config.get('datapoint_mappings', {})
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address matches any datapoint mapping."""
        return address['DatapointType'] in self.datapoint_mappings
    
    def generate(self, address: Dict, co: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generate OpenHAB configuration based on datapoint mappings.
        
        Returns:
            Dictionary with 'item_type', 'thing_info', 'metadata', etc.
        """
        dpt = address['DatapointType']
        mapping = self.datapoint_mappings.get(dpt)
        
        if not mapping:
            logger.warning(f"No mapping found for DPT {dpt}")
            return None
        
        # Build thing info
        ga_prefix = mapping['ga_prefix']
        thing_info = ''
        
        if "=" in ga_prefix:
            # Format: "position=5.001"
            split_info = ga_prefix.split("=")
            thing_info = f'{split_info[0]}="{split_info[1]}:{address["Address"]}"'
        else:
            # Format: "9.001"
            thing_info = f'ga="{ga_prefix}:{address["Address"]}"'
        
        basename = address['Group name']
        
        result = {
            'item_type': mapping['item_type'],
            'semantic_info': mapping['semantic_info'],
            'item_icon': mapping['item_icon'],
            'metadata': mapping['metadata'],
            'equipment': '',
            'thing_info': thing_info
        }
        
        # Check for special configurations based on item type
        item_type_lower = mapping['item_type'].lower()
        if item_type_lower in self.config.get('defines', {}):
            define = self.config['defines'][item_type_lower]
            
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
        
        # Special handling for temperature setpoints
        if 'Soll' in basename and 'Temperature' in result['semantic_info']:
            result['semantic_info'] = result['semantic_info'].replace('Measurement', 'Setpoint')
            if 'CurrentTemperature' in result.get('metadata', ''):
                result['metadata'] = result['metadata'].replace('CurrentTemperature', 'TargetTemperature')
        
        # Add homekit/alexa from mapping if not already set
        if self.config.get('homekit_enabled', False) and mapping.get('homekit'):
            if mapping['homekit'] not in result['metadata']:
                result['metadata'] += mapping['homekit']
        
        if self.config.get('alexa_enabled', False) and mapping.get('alexa'):
            if mapping['alexa'] not in result['metadata']:
                result['metadata'] += mapping['alexa']
        
        # Handle window contacts specially
        if dpt == 'DPST-1-19':  # Window contact
            result['equipment'] = 'Window'
        
        return result
