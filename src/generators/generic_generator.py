"""Generic generator for devices using datapoint_mappings"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult

logger = logging.getLogger(__name__)


class GenericGenerator(BaseDeviceGenerator):
    """Generic generator for devices defined in datapoint_mappings config"""
    
    def __init__(self, config: Dict, all_addresses: list):
        super().__init__(config, all_addresses)
        self.datapoint_mappings = config.get('datapoint_mappings', {})
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address matches any datapoint mapping."""
        return address['DatapointType'] in self.datapoint_mappings
    
    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration based on datapoint mappings.
        
        Returns:
            DeviceGeneratorResult with generated configuration
        """
        if context is None:
            context = {}
            
        result = DeviceGeneratorResult()
        dpt = address.get('DatapointType', '')
        mapping = self.datapoint_mappings.get(dpt)
        
        if not mapping:
            logger.warning(f"No mapping found for DPT {dpt}")
            return None
        
        # Build thing info
        ga_prefix = mapping['ga_prefix']
        thing_info = ''
        
        main_addr = address.get('Address', '')
        if "=" in ga_prefix:
            # Format: "position=5.001"
            split_info = ga_prefix.split("=")
            thing_info = f'{split_info[0]}="{split_info[1]}:{main_addr}"'
        else:
            # Format: "9.001"
            thing_info = f'ga="{ga_prefix}:{main_addr}"'
        
        basename = address.get('Group_name') or address.get('Group name', 'Generic')
        item_name = context.get('item_name', basename.replace(' ', '_'))
        
        # Map fields
        result.item_type = mapping['item_type']
        result.semantic_info = mapping['semantic_info']
        result.icon = mapping['item_icon']
        result.item_icon = mapping['item_icon']
        result.thing_info = thing_info
        result.item_name = item_name
        result.label = basename
        result.success = True
        result.used_addresses.append(main_addr)
        
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
                                result.equipment = value
                            elif key == 'item_icon':
                                result.item_icon = value
                                result.icon = value
                            elif key == 'semantic_info':
                                result.semantic_info = value
                            elif key == 'homekit' and self.config.get('homekit_enabled', False):
                                result.metadata['homekit'] = value
                            elif key == 'alexa' and self.config.get('alexa_enabled', False):
                                result.metadata['alexa'] = value
                        break
        
        # Special handling for temperature setpoints
        if 'Soll' in basename and 'Temperature' in result.semantic_info:
            result.semantic_info = result.semantic_info.replace('Measurement', 'Setpoint')
            if 'homekit' in result.metadata and result.metadata['homekit'] == 'CurrentTemperature':
                result.metadata['homekit'] = 'TargetTemperature'
        
        # Add homekit/alexa from mapping if not already set
        if self.config.get('homekit_enabled', False) and mapping.get('homekit'):
            if 'homekit' not in result.metadata:
                result.metadata['homekit'] = mapping['homekit']
        
        if self.config.get('alexa_enabled', False) and mapping.get('alexa'):
            if 'alexa' not in result.metadata:
                result.metadata['alexa'] = mapping['alexa']
        
        # Handle window contacts specially
        if dpt == 'DPST-1-19':  # Window contact
            result.equipment = 'Window'
            
        return result
