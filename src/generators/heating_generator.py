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
        define = self.config['defines']['heating']
        
        # Find communication object if not provided
        if not co:
            co = self.get_co_by_functiontext(address, define['level_suffix'])
            if not co:
                logger.debug(f"No valid CO found for heating {address['Address']}")
                return None
        
        basename = address['Group name']
        
        # Find status address (optional)
        status = self.get_address_from_dco_enhanced(co, 'status_level_suffix', define)
        
        # Determine GA and item type based on DPT
        ga = "5.010"
        item_type = "Number:Dimensionless"
        
        if address['DatapointType'] == 'DPST-20-102':
            ga = "20.102"
            item_type = "Number"
        
        result = {
            'item_type': item_type,
            'equipment': 'HVAC',
            'semantic_info': '["HVAC"]',
            'item_icon': 'heating_mode',
            'metadata': ', stateDescription=""[options="NULL=unbekannt ...,1=Komfort,2=Standby,3=Nacht,4=Frostschutz"], commandDescription=""[options="1=Komfort,2=Standby,3=Nacht,4=Frostschutz"], listWidget=""[iconUseState="true"]',
            'thing_info': ''
        }
        
        if status:
            self.mark_address_used(status['Address'])
            result['thing_info'] = f'ga="{ga}:{address["Address"]}+<{status["Address"]}"'
        else:
            result['thing_info'] = f'ga="{ga}:{address["Address"]}"'
        
        # Homekit/Alexa metadata
        if self.config.get('homekit_enabled', False):
            result['metadata'] += ', homekit = "CurrentHeatingCoolingMode, TargetHeatingCoolingMode" [OFF="4", HEAT="1", COOL="2"]'
            result['equipment_homekit'] = 'homekit = "Thermostat"'
        
        if self.config.get('alexa_enabled', False):
            result['metadata'] += ', alexa = "HeatingCoolingMode" [OFF="4", HEAT="1", COOL="2"]'
            result['equipment_alexa'] = 'alexa = "Thermostat"'
        
        return result
