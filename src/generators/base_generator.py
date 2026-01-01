"""Base generator class for device type generators"""

import logging
from typing import Optional, Dict, List
from abc import ABC, abstractmethod

from config import normalize_string

logger = logging.getLogger(__name__)


class BaseDeviceGenerator(ABC):
    """Abstract base class for device generators"""
    
    def __init__(self, config: Dict, all_addresses: List[Dict]):
        """
        Initialize generator.
        
        Args:
            config: Configuration dictionary
            all_addresses: List of all available KNX addresses
        """
        self.config = config
        self.all_addresses = all_addresses
        self.used_addresses = []
        
    @abstractmethod
    def can_handle(self, address: Dict) -> bool:
        """
        Check if this generator can handle the given address.
        
        Args:
            address: KNX address dictionary
            
        Returns:
            True if this generator can process the address
        """
        pass
    
    @abstractmethod
    def generate(self, address: Dict, co: Dict) -> Optional[Dict]:
        """
        Generate OpenHAB configuration for the address.
        
        Args:
            address: KNX address dictionary
            co: Communication object
            
        Returns:
            Dictionary with 'item', 'thing', 'sitemap' keys or None
        """
        pass
    
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
            
        for co in cos["communication_object"]:
            if checkwriteflag:
                if "flags" in co:
                    if "write" in co["flags"]:
                        if not co["flags"]["write"]:
                            continue
            
            if normalize_string(co["function_text"]) in config_functiontexts:
                return co
                
        return None
    
    def get_co_flags(self, co: Dict) -> Optional[Dict]:
        """
        Extract flags from communication object.
        
        Args:
            co: Communication object
            
        Returns:
            Dictionary with flags or None
        """
        if "flags" not in co:
            return None
        
        return {
            "read": co["flags"].get("read", False),
            "write": co["flags"].get("write", False),
            "transmit": co["flags"].get("transmit", False),
            "update": co["flags"].get("update", False)
        }
    
    def flags_match(self, co_flags: Optional[Dict], expected_flags: Optional[Dict]) -> bool:
        """
        Compare CO flags with expected flags.
        
        Args:
            co_flags: Actual flags from CO
            expected_flags: Expected flags from config
            
        Returns:
            True if all expected flags match
        """
        if not co_flags or not expected_flags:
            return True
        
        for key, expected_value in expected_flags.items():
            if co_flags.get(key, False) != expected_value:
                return False
        
        return True
    
    def get_address_from_dco_enhanced(self, co: Dict, config_key: str, 
                                      define: Dict) -> Optional[Dict]:
        """
        Enhanced search for group addresses with flag and DPT filtering.
        
        Args:
            co: Base communication object
            config_key: Key in the define config (e.g. 'status_suffix')
            define: Definition from config (e.g. config['defines']['dimmer'])
            
        Returns:
            Found group address or None
        """
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
        sorted_dcos = sorted(co["device_communication_objects"], 
                           key=lambda x: int(x.get("number", 999999)))
        
        for dco in sorted_dcos:
            # Filter 1: Channel/Text match
            if group_channel:
                if group_channel != dco.get("channel"):
                    continue
            elif group_text:
                if group_text != dco.get("text"):
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
                dco_flags = self.get_co_flags(dco)
                if not self.flags_match(dco_flags, expected_flags):
                    continue
            
            # Filter 4: Function text
            if not expected_dpts and not expected_flags:
                if function_texts:
                    if normalize_string(dco.get("function_text", "")) not in function_texts:
                        continue
            
            # Search for group address
            search_address = [x for x in self.all_addresses 
                            if x["Address"] in dco.get('group_address_links', [])]
            
            if search_address:
                candidates.append({
                    'dco': dco,
                    'addresses': search_address,
                    'channel_match': group_channel == dco.get("channel") if group_channel else False
                })
        
        if not candidates:
            return None
        
        # Prioritization
        candidates.sort(key=lambda x: (
            not x['channel_match'],
            len(x['addresses'])
        ))
        
        best_candidate = candidates[0]
        if len(best_candidate['addresses']) == 1:
            return best_candidate['addresses'][0]
        else:
            return min(best_candidate['addresses'],
                      key=lambda sa: len(sa.get("communication_object", [])))
    
    def mark_address_used(self, address: str):
        """Mark an address as used to avoid duplicate processing."""
        if address not in self.used_addresses:
            self.used_addresses.append(address)
    
    def is_address_used(self, address: str) -> bool:
        """Check if an address has already been used."""
        return address in self.used_addresses
