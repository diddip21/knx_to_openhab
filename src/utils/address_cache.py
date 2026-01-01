"""Address cache for performance optimization"""

import logging
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class AddressCache:
    """Cache for KNX address lookups to improve performance"""
    
    def __init__(self):
        """Initialize empty cache."""
        self.by_address = {}  # address string -> address dict
        self.by_dpt = defaultdict(list)  # DPT -> list of addresses
        self.by_name = {}  # group name -> address dict
        self.co_cache = {}  # address -> communication object
        self._hit_count = 0
        self._miss_count = 0
    
    def build_index(self, addresses: List[Dict]):
        """
        Build cache indices from address list.
        
        Args:
            addresses: List of KNX address dictionaries
        """
        logger.info(f"Building address cache for {len(addresses)} addresses")
        
        for addr in addresses:
            address_str = addr.get('Address')
            dpt = addr.get('DatapointType')
            name = addr.get('Group name')
            
            if address_str:
                self.by_address[address_str] = addr
            
            if dpt:
                self.by_dpt[dpt].append(addr)
            
            if name:
                self.by_name[name] = addr
        
        logger.info(f"Cache built: {len(self.by_address)} addresses, "
                   f"{len(self.by_dpt)} DPT types, {len(self.by_name)} names")
    
    def get_by_address(self, address: str) -> Optional[Dict]:
        """
        Get address by address string.
        
        Args:
            address: KNX address string (e.g., "1/2/3")
            
        Returns:
            Address dictionary or None
        """
        result = self.by_address.get(address)
        if result:
            self._hit_count += 1
        else:
            self._miss_count += 1
        return result
    
    def get_by_dpt(self, dpt: str) -> List[Dict]:
        """
        Get all addresses with specific DPT.
        
        Args:
            dpt: Datapoint type string (e.g., "DPST-1-1")
            
        Returns:
            List of address dictionaries
        """
        result = self.by_dpt.get(dpt, [])
        if result:
            self._hit_count += 1
        else:
            self._miss_count += 1
        return result
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        """
        Get address by group name.
        
        Args:
            name: Group name string
            
        Returns:
            Address dictionary or None
        """
        result = self.by_name.get(name)
        if result:
            self._hit_count += 1
        else:
            self._miss_count += 1
        return result
    
    def find_related(self, base_name: str, suffixes: List[str], 
                     replacements: Optional[List[str]] = None) -> Optional[Dict]:
        """
        Find address related to base name by suffix/replacement.
        
        Args:
            base_name: Base group name
            suffixes: List of suffixes to try
            replacements: Optional list of strings to replace in base_name
            
        Returns:
            Found address or None
        """
        if replacements is None:
            replacements = []
        
        # Try direct suffix matches
        for suffix in suffixes:
            # Try with space
            candidate = f"{base_name} {suffix}"
            result = self.get_by_name(candidate)
            if result:
                return result
            
            # Try without space
            candidate = f"{base_name}{suffix}"
            result = self.get_by_name(candidate)
            if result:
                return result
        
        # Try replacements
        for replacement in replacements:
            for suffix in suffixes:
                candidate = base_name.replace(replacement, suffix)
                result = self.get_by_name(candidate)
                if result:
                    return result
        
        self._miss_count += 1
        return None
    
    def cache_co(self, address: str, co: Dict):
        """
        Cache communication object for address.
        
        Args:
            address: Address string
            co: Communication object dictionary
        """
        self.co_cache[address] = co
    
    def get_co(self, address: str) -> Optional[Dict]:
        """
        Get cached communication object.
        
        Args:
            address: Address string
            
        Returns:
            Cached CO or None
        """
        return self.co_cache.get(address)
    
    def remove_address(self, address: str):
        """
        Remove address from cache (used when marking as processed).
        
        Args:
            address: Address string to remove
        """
        if address in self.by_address:
            addr_dict = self.by_address[address]
            dpt = addr_dict.get('DatapointType')
            name = addr_dict.get('Group name')
            
            # Remove from all indices
            del self.by_address[address]
            
            if dpt and dpt in self.by_dpt:
                self.by_dpt[dpt] = [a for a in self.by_dpt[dpt] 
                                   if a.get('Address') != address]
            
            if name and name in self.by_name:
                del self.by_name[name]
    
    def get_statistics(self) -> Dict:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with hit/miss counts and ratios
        """
        total = self._hit_count + self._miss_count
        hit_rate = (self._hit_count / total * 100) if total > 0 else 0
        
        return {
            'hits': self._hit_count,
            'misses': self._miss_count,
            'total': total,
            'hit_rate': f"{hit_rate:.1f}%",
            'cached_addresses': len(self.by_address),
            'cached_dpts': len(self.by_dpt),
            'cached_cos': len(self.co_cache)
        }
    
    def clear(self):
        """Clear all caches."""
        self.by_address.clear()
        self.by_dpt.clear()
        self.by_name.clear()
        self.co_cache.clear()
        self._hit_count = 0
        self._miss_count = 0
        logger.info("Cache cleared")
