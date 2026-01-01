"""Base generator class for all device generators"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class DeviceGeneratorResult:
    """Result of a device generation operation"""
    
    def __init__(self):
        self.thing: str = ""
        self.item: str = ""
        self.sitemap: str = ""
        self.used_addresses: List[str] = []
        self.success: bool = False
        self.error_message: Optional[str] = None
        self.metadata: Dict[str, Any] = {}


class BaseDeviceGenerator(ABC):
    """Base class for all device type generators"""
    
    def __init__(self, config: Dict, all_addresses: List[Dict]):
        """
        Initialize generator.
        
        Args:
            config: Configuration dictionary from config.json
            all_addresses: List of all available KNX group addresses
        """
        self.config = config
        self.all_addresses = all_addresses
        self.address_cache: Dict[str, Optional[Dict]] = {}
        
    @abstractmethod
    def can_handle(self, address: Dict) -> bool:
        """
        Check if this generator can handle the given address.
        
        Args:
            address: KNX group address dictionary
            
        Returns:
            True if this generator can handle the address
        """
        pass
    
    @abstractmethod
    def generate(self, address: Dict, context: Dict) -> DeviceGeneratorResult:
        """
        Generate OpenHAB configuration for the address.
        
        Args:
            address: KNX group address to process
            context: Context information (floor, room, etc.)
            
        Returns:
            DeviceGeneratorResult with generated configuration
        """
        pass
    
    def find_related_address(self, base_address: Dict, config_key: str, 
                            define: Dict) -> Optional[Dict]:
        """
        Find related address using enhanced DPT and flag filtering.
        
        This replaces the old get_address_from_dco_enhanced logic.
        
        Args:
            base_address: Base KNX address to search from
            config_key: Configuration key (e.g., 'status_suffix')
            define: Device definition from config
            
        Returns:
            Related address or None
        """
        cache_key = f"{base_address['Address']}_{config_key}"
        
        if cache_key in self.address_cache:
            return self.address_cache[cache_key]
        
        result = self._search_related_address(base_address, config_key, define)
        self.address_cache[cache_key] = result
        return result
    
    def _search_related_address(self, co: Dict, config_key: str, 
                               define: Dict) -> Optional[Dict]:
        """Internal method to search for related addresses"""
        # Extract configuration
        function_texts_key = config_key
        dpts_key = config_key.replace('_suffix', '_dpts')
        flags_key = config_key.replace('_suffix', '_flags')
        
        function_texts = define.get(function_texts_key, [])
        expected_dpts = define.get(dpts_key, None)
        expected_flags = define.get(flags_key, None)
        
        group_channel = co.get("channel")
        group_text = co.get("text")
        
        if "device_communication_objects" not in co:
            return None
        
        candidates = []
        sorted_dcos = sorted(
            co["device_communication_objects"], 
            key=lambda x: int(x.get("number", 999999))
        )
        
        for dco in sorted_dcos:
            # Filter 1: Channel/Text match
            if group_channel and group_channel != dco.get("channel"):
                continue
            elif group_text and group_text != dco.get("text"):
                continue
            
            # Filter 2: DPT filtering
            if expected_dpts:
                dco_dpts = dco.get("dpts", [])
                if dco_dpts:
                    dpt = dco_dpts[0]
                    dco_dpst = f'DPST-{dpt["main"]}-{dpt.get("sub", 0)}'
                    if dco_dpst not in expected_dpts:
                        continue
                else:
                    continue
            
            # Filter 3: Flag filtering
            if expected_flags:
                dco_flags = self._get_co_flags(dco)
                if not self._flags_match(dco_flags, expected_flags):
                    continue
            
            # Filter 4: Function text (fallback)
            if not expected_dpts and not expected_flags:
                if function_texts:
                    from config import normalize_string
                    if normalize_string(dco.get("function_text", "")) not in function_texts:
                        continue
            
            # Search for group address
            search_address = [
                x for x in self.all_addresses 
                if x["Address"] in dco.get('group_address_links', [])
            ]
            
            if search_address:
                candidates.append({
                    'dco': dco,
                    'addresses': search_address,
                    'channel_match': group_channel == dco.get("channel") if group_channel else False
                })
        
        if not candidates:
            return None
        
        # Prioritization: Channel match, then fewest linked addresses
        candidates.sort(key=lambda x: (not x['channel_match'], len(x['addresses'])))
        
        best_candidate = candidates[0]
        if len(best_candidate['addresses']) == 1:
            return best_candidate['addresses'][0]
        else:
            return min(
                best_candidate['addresses'],
                key=lambda sa: len(sa.get("communication_object", []))
            )
    
    @staticmethod
    def _get_co_flags(co: Dict) -> Optional[Dict[str, bool]]:
        """Extract flags from communication object"""
        if "flags" not in co:
            return None
        
        return {
            "read": co["flags"].get("read", False),
            "write": co["flags"].get("write", False),
            "transmit": co["flags"].get("transmit", False),
            "update": co["flags"].get("update", False)
        }
    
    @staticmethod
    def _flags_match(co_flags: Optional[Dict], expected_flags: Optional[Dict]) -> bool:
        """Compare CO flags with expected flags"""
        if not co_flags or not expected_flags:
            return True
        
        for key, expected_value in expected_flags.items():
            if co_flags.get(key, False) != expected_value:
                return False
        
        return True
    
    def get_co_by_functiontext(self, cos: Dict, config_functiontexts: List[str], 
                               checkwriteflag: bool = True) -> Optional[Dict]:
        """
        Find communication object by function text.
        
        Args:
            cos: Communication objects dictionary
            config_functiontexts: List of function texts to search for
            checkwriteflag: Whether to check write flag
            
        Returns:
            Found communication object or None
        """
        if "communication_object" not in cos:
            return None
        
        from config import normalize_string
        
        for co in cos["communication_object"]:
            if checkwriteflag:
                if "flags" in co and "write" in co["flags"]:
                    if not co["flags"]["write"]:
                        continue
            
            if normalize_string(co["function_text"]) in config_functiontexts:
                return co
        
        return None
