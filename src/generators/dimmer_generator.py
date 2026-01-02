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
