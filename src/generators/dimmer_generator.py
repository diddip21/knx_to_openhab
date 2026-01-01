"""Generator for dimmer devices"""

import logging
from typing import Optional, Dict

from .base_generator import BaseDeviceGenerator
from utils import get_datapoint_type

logger = logging.getLogger(__name__)


class DimmerGenerator(BaseDeviceGenerator):
    """Generator for KNX dimmer devices"""
    
    def can_handle(self, address: Dict) -> bool:
        """Check if address is a dimmer."""
        return address['DatapointType'] == get_datapoint_type('dimmer')
    
    def generate(self, address: Dict, co: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generate OpenHAB configuration for a dimmer.
        
        Returns:
            Dictionary with 'item_type', 'thing_info', 'metadata', etc.
        """
        define = self.config['defines']['dimmer']
        
        # Find communication object if not provided
        if not co:
            co = self.get_co_by_functiontext(address, define['absolut_suffix'])
            if not co:
                logger.debug(f"No valid CO found for dimmer {address['Address']}")
                return None
        
        basename = address['Group name']
        
        # Find status address
        status = self.get_address_from_dco_enhanced(co, 'status_suffix', define)
        if not status:
            logger.error(f"Incomplete dimmer: {basename} / {address['Address']} - missing status")
            return None
        
        self.mark_address_used(status['Address'])
        
        # Drop unnecessary addresses
        for drop_name in define['drop']:
            drop_addr = self._find_related_address(basename, drop_name, define['absolut_suffix'])
            if drop_addr:
                self.mark_address_used(drop_addr['Address'])
        
        # Build configuration
        result = {
            'item_type': 'Dimmer',
            'equipment': 'Lightbulb',
            'semantic_info': '["Light"]',
            'item_icon': 'light',
            'metadata': '',
            'thing_info': f'position="{address["Address"]}+<{status["Address"]}"'
        }
        
        # Optional: Relative dimming
        relative_cmd = self.get_address_from_dco_enhanced(co, 'relativ_suffix', define)
        if relative_cmd:
            self.mark_address_used(relative_cmd['Address'])
            result['thing_info'] += f', increaseDecrease="{relative_cmd["Address"]}"'
        
        # Optional: Switch functionality
        switch_cmd = self.get_address_from_dco_enhanced(co, 'switch_suffix', define)
        if switch_cmd:
            self.mark_address_used(switch_cmd['Address'])
            switch_status = self.get_address_from_dco_enhanced(co, 'switch_status_suffix', define)
            
            switch_option = f'{switch_cmd["Address"]}'
            if switch_status:
                self.mark_address_used(switch_status['Address'])
                switch_option += f'+<{switch_status["Address"]}'
            
            result['thing_info'] += f', switch="{switch_option}"'
        
        # Homekit/Alexa metadata
        if self.config.get('homekit_enabled', False):
            result['metadata'] += ', homekit="Lighting, Lighting.Brightness"'
        if self.config.get('alexa_enabled', False):
            result['metadata'] += ', alexa = "Light"'
        
        return result
    
    def _find_related_address(self, basename: str, suffix: str, replace: str) -> Optional[Dict]:
        """Find related address by name pattern."""
        suffix_list = [suffix] if isinstance(suffix, str) else suffix
        replace_list = [replace] if isinstance(replace, str) else replace
        
        for addr in self.all_addresses:
            if addr['Group name'] == basename:
                continue
            
            for s in suffix_list:
                if addr['Group name'] in (basename + s, basename + ' ' + s):
                    return addr
                
                for r in replace_list:
                    if addr['Group name'] == basename.replace(r, s):
                        return addr
        
        return None
