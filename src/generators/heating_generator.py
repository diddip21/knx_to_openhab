"""Generator for heating/HVAC devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class HeatingGenerator(BaseDeviceGenerator):
    """Generator for KNX heating/HVAC devices"""

    def can_handle(self, address: Dict) -> bool:
        """Check if address is heating related."""
        heating_type = get_datapoint_type('heating')
        heating_mode_type = get_datapoint_type('heating_mode')
        return address['DatapointType'] in (heating_type, heating_mode_type)

    def generate(self, address: Dict, co: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generate OpenHAB configuration for heating device.

        Returns:
            Dictionary with 'item_type', 'thing_info', 'metadata', etc.
        """
        define = self.config.get('defines', {}).get('heating', {})
        # Find communication object if not provided
        if not co:
            co = self.get_co_by_functiontext(address, define['level_suffix'])
            if not co:
                logger.debug(f"No valid CO found for heating {address['Address']}")
                return None

        basename = address.get('Group_name', 'Heating')

        # Find status address (optional)
        status = None  # For now, set status to None

        # Determine GA and item type based on DPT
        ga = "5.010"
        item_type = "Number:Dimensionless"

        if address['DatapointType'] == 'DPST-20-102':
            ga = "20.102"
            item_type = "Number"

        result = {
            'item_type': item_type,
            'thing_info': {
                'ga': ga,
                'position': define['position'],
                'dpt': address['DatapointType']
            },
            'metadata': {
                'basename': basename,
                'room': address['Floor_name'],
                'homekit': define.get('homekit', {})
            }
        }

        if status:
            result['thing_info']['status_ga'] = status

        self.mark_address_used(address)
        if co:
            self.mark_address_used(co)

        return result
