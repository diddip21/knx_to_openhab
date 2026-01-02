"""Generator for rollershutter/blind devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class RollershutterGenerator(BaseDeviceGenerator):
    """Generator for KNX rollershutter/blind devices"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a rollershutter."""
        return address['DatapointType'] == get_datapoint_type('rollershutter')
    
    def generate(self, address: Dict, co: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generate OpenHAB configuration for a rollershutter.
        
        Returns:
            Dictionary with 'item_type', 'thing_info', 'metadata', etc.
        """
        define = self.config.get('defines', {}).get('rollershutter', {})        
        # Find communication object if not provided
        if not co:
            co = self.get_co_by_functiontext(address, define['up_down_suffix'])
            if not co:
                logger.debug(f"No valid CO found for rollershutter {address['Address']}")
                return None
        
        basename = address.get('Group_name', 'RollerShutter')
