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
    
    def generate(self, address: Dict, context: Optional[Dict] = None) -> DeviceGeneratorResult:        """
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
            context = {
                'item_name': address.get('Group_name', '').replace(' ', '_'),
                'floor_nr': 0,
                'room_nr': 0,
                'floor_name': address.get('Floor_name', 'Unknown'),
                'room_name': address.get('Room_name', 'Unknown')
            }

        result = DeviceGeneratorResult()
        
        define = self.config['defines']['dimmer']
        
        # Find the communication object
        co = self.get_co_by_functiontext(address, define['absolut_suffix'])
        if not co:
            result.error_message = f"No communication object found for dimmer {address['Address']}"
            return result
        
        basename = address['Group name']
        
        # Find related addresses
        status = self.find_related_address(co, 'status_suffix', define)
        
        if not status:
            result.error_message = f"Incomplete dimmer: missing status for {basename}"
            logger.error(result.error_message)
            return result
        
        # Mark addresses as used
        result.used_addresses.append(address['Address'])
        result.used_addresses.append(status['Address'])
        
        # Handle drop addresses
        for drop_name in define['drop']:
            drop_addr = self._find_by_name(basename, drop_name, define['absolut_suffix'])
            if drop_addr:
                result.used_addresses.append(drop_addr['Address'])
        
        # Build configuration options
        options = self._build_dimmer_options(co, define, result)
        
        # Generate thing, item, sitemap
        result.thing = self._generate_thing(
            context['item_name'],
            address,
            status,
            options
        )
        
        result.item = self._generate_item(
                    # Create default context if not provided
        if context is None:
            context = {
                'item_name': address.get('Group_name', '').replace(' ', '_'),
                'floor_nr': 0,
                'room_nr': 0,
                'floor_name': address.get('Floor_name', 'Unknown'),
                'room_name': address.get('Room_name', 'Unknown')
            }

            context['item_name'],
            address['Group name'],
            context['floor_nr'],
            context['room_nr'],
            context
        )
        
        result.sitemap = self._generate_sitemap(
            context['item_name'],
            address['Group name'],
            context
        )
        
        # Store metadata
        result.metadata = {
            'device_type': 'dimmer',
            'equipment': 'Lightbulb',
            'semantic_info': '["Light"]',
            'item_icon': 'light'
        }
        
        result.success = True
        return result
    
    def _build_dimmer_options(self, co: Dict, define: Dict, 
                             result: DeviceGeneratorResult) -> Dict[str, str]:
        """Build dimmer-specific options (relative, switch, etc.)"""
        options = {}
        
        # Relative dimming
        relative_command = self.find_related_address(co, 'relativ_suffix', define)
        if relative_command:
            result.used_addresses.append(relative_command['Address'])
            options['relative'] = f", increaseDecrease=\"{relative_command['Address']}\""
        
        # Switch functionality
        switch_command = self.find_related_address(co, 'switch_suffix', define)
        if switch_command:
            result.used_addresses.append(switch_command['Address'])
            
            switch_status = self.find_related_address(co, 'switch_status_suffix', define)
            switch_option_status = ""
            if switch_status:
                result.used_addresses.append(switch_status['Address'])
                switch_option_status = f"+<{switch_status['Address']}"
            
            options['switch'] = f", switch=\"{switch_command['Address']}{switch_option_status}\""
        
        return options
    
    def _generate_thing(self, item_name: str, address: Dict, 
                       status: Dict, options: Dict) -> str:
        """Generate thing configuration"""
        relative_opt = options.get('relative', '')
        switch_opt = options.get('switch', '')
        
        thing = (
            f"Type dimmer    :   {item_name}   \"{address['Group name']}\"   "
            f"[ position=\"{address['Address']}+<{status['Address']}\""
            f"{switch_opt}{relative_opt} ]\n"
        )
        return thing
    
    def _generate_item(self, item_name: str, label: str, floor_nr: int, 
                      room_nr: int, context: Dict) -> str:
        """Generate item configuration"""
        # Check for equipment grouping
        equipment_group = context.get('equipment_group', '')
        root = f"map{floor_nr}_{room_nr}"
        
        if equipment_group:
            root = equipment_group
        
        homekit_meta = ""
        alexa_meta = ""
        
        if context.get('homekit_enabled'):
            homekit_instance = context.get('homekit_instance', 1)
            homekit_meta = f', homekit="Lighting, Lighting.Brightness" [Instance={homekit_instance}]'
        
        if context.get('alexa_enabled'):
            alexa_meta = ', alexa = "Light"'
        
        item = (
            f"Dimmer   {item_name}   \"{label}\"   <light>   ({root})   [\"Light\"]    "
            f"{{ channel=\"knx:device:bridge:generic:{item_name}\"{homekit_meta}{alexa_meta} }}\n"
        )
        return item
    
    def _generate_sitemap(self, item_name: str, label: str, context: Dict) -> str:
        """Generate sitemap entry"""
        visibility = context.get('visibility', '')
        return f"        Default item={item_name} label=\"{label}\" {visibility}\n"
    
    def _find_by_name(self, base_name: str, suffix: str, replace: str) -> Optional[Dict]:
        """Find address by name pattern (legacy compatibility)"""
        if isinstance(suffix, str):
            suffix = [suffix]
        if isinstance(replace, str):
            replace = [replace]
        
        for addr in self.all_addresses:
            if addr['Group name'] == base_name:
                continue
            
            for s in suffix:
                if addr['Group name'] == base_name + s:
                    return addr
                if addr['Group name'] == base_name + ' ' + s:
                    return addr
                
                for r in replace:
                    if addr['Group name'] == base_name.replace(r, s):
                        return addr
        
        return None
