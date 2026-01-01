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
        
        basename = address['Group name']
        up_down_address = address
        
        # Drop unnecessary addresses
        for drop_name in define['drop']:
            drop_addr = self._find_related_address(basename, drop_name, define['up_down_suffix'])
            if drop_addr:
                self.mark_address_used(drop_addr['Address'])
        
        # Build basic configuration
        self.mark_address_used(up_down_address['Address'])
        
        result = {
            'item_type': 'Rollershutter',
            'equipment': 'Blinds',
            'semantic_info': '["Blinds"]',
            'item_icon': 'rollershutter',
            'metadata': '',
            'thing_info': f'upDown="{up_down_address["Address"]}"'
        }
        
        # Optional: Stop command
        stop_cmd = self.get_address_from_dco_enhanced(co, 'stop_suffix', define)
        if stop_cmd:
            self.mark_address_used(stop_cmd['Address'])
            result['thing_info'] += f', stopMove="{stop_cmd["Address"]}"'
        
        # Optional: Absolute position
        absolute_position = self.get_address_from_dco_enhanced(co, 'absolute_position_suffix', define)
        position_status = self.get_address_from_dco_enhanced(co, 'status_suffix', define)
        
        if absolute_position or position_status:
            position_str = ''
            if absolute_position:
                self.mark_address_used(absolute_position['Address'])
                position_str = absolute_position['Address']
            
            if position_status:
                self.mark_address_used(position_status['Address'])
                if absolute_position:
                    position_str += f'+<{position_status["Address"]}'
                else:
                    position_str = f'<{position_status["Address"]}'
            
            result['thing_info'] += f', position="{position_str}"'
        
        # Homekit/Alexa metadata
        if self.config.get('homekit_enabled', False):
            result['metadata'] += ', homekit = "CurrentPosition, TargetPosition, PositionState"'
            result['equipment_homekit'] = 'homekit = "WindowCovering"'
        
        if self.config.get('alexa_enabled', False):
            result['metadata'] += ', alexa = "PositionState"'
            result['equipment_alexa'] = 'alexa = "Blind"'
        
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
