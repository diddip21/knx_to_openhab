"""KNX to OpenHAB Generator - Refactored modular structure"""

__version__ = "2.0.0"

# Public API for backward compatibility
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


def gen_building_new(floors, all_addresses, config):
    """
    New implementation of gen_building using refactored structure.
    
    This function provides backward compatibility with the legacy gen_building()
    but uses the new modular generator architecture internally.
    
    Args:
        floors: List of floor dictionaries with rooms and addresses
        all_addresses: List of all KNX group addresses
        config: Configuration dictionary
    
    Returns:
        Tuple of (items, sitemap, things) strings
    """
    from .building_generator import BuildingGenerator
    
    logger.info("Using new refactored building generator")
    
    # Initialize the new building generator
    building_gen = BuildingGenerator(config, all_addresses)
    
    # Generate the building configuration
    items, sitemap, things = building_gen.generate(floors)
    
    # Remove used addresses from all_addresses for backward compatibility
    # This allows check_unused_addresses() in ets_to_openhab to work correctly
    for addr_str in building_gen.used_addresses:
        found = next((x for x in all_addresses if x['Address'] == addr_str), None)
        if found:
            all_addresses.remove(found)
            
    return items, sitemap, things


__all__ = ['gen_building_new', '__version__']
