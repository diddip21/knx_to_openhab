"""Generator for heating/HVAC devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator, DeviceGeneratorResult
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class HeatingGenerator(BaseDeviceGenerator):
    """Generator for KNX heating/HVAC devices"""

    def can_handle(self, address: Dict) -> bool:
        """Check if address is heating related."""
        heating_type = get_datapoint_type('heating')
        heating_mode_type = get_datapoint_type('heating_mode')
        # Also include DPST-9-1 which is common for temperature sensors used in heating
        return address['DatapointType'] in (heating_type, heating_mode_type, 'DPST-9-1', 'DPST-5-1')

    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration for heating device.

        Returns:
            DeviceGeneratorResult with generated configuration
        """
        if context is None:
            context = {}
            
        result = DeviceGeneratorResult()
        define = self.config.get('defines', {}).get('heating', {})
        if not define:
            logger.warning(f"No heating definition found in config")
            return result

        basename = address.get('Group_name') or address.get('Group name', 'Heating')
        
        # Determine GA and item type based on DPT
        ga = "5.010"
        item_type = "Number:Dimensionless"

        dpt = address.get('DatapointType', '')
        if dpt == 'DPST-20-102':
            ga = "20.102"
            item_type = "Number"
        elif dpt == 'DPST-9-1':
            ga = "9.001"
            item_type = "Number:Temperature"
        elif dpt == 'DPST-5-1':
            ga = "5.001"
            item_type = "Number:Dimensionless"

        result.item_type = item_type
        result.success = True
        result.label = basename
        result.item_name = context.get('item_name', basename.replace(' ', '_'))
        result.icon = define.get('icon', 'heating')
        result.item_icon = define.get('icon', 'heating')
        
        main_addr = address.get('Address', '')
        result.used_addresses.append(main_addr)
        
        # Find communication object
        co = address.get('communication_object', [{}])[0] if address.get('communication_object') else {}
        
        # Find status address
        status_address = self.find_related_address(
            co,
            'status_level_suffix',
            define,
            base_address_str=main_addr
        )

        if status_address:
            status_addr = status_address.get('Address', '')
            result.thing_info = f'ga="{ga}:{main_addr}+<{status_addr}"'
            result.used_addresses.append(status_addr)
        else:
            result.thing_info = f'ga="{ga}:{main_addr}"'

        # Metadata for Homekit if enabled
        if self.config.get('homekit_enabled', False):
            result.metadata['homekit'] = 'Thermostat'

        return result
