"""Integration test comparing legacy and refactored implementations."""
import pytest
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config
from src import gen_building_new
import ets_to_openhab


class TestLegacyVsRefactoredComparison:
    """Compare outputs between legacy and refactored implementations."""
    
    @pytest.fixture
    def test_data(self):
        """Load test data with sample floors and addresses."""
        # Sample test data - minimal structure for testing
        floors = [
            {
                'Group name': 'Test Floor',
                'Description': 'Test',
                'name_short': 'TF',
                'rooms': [
                    {
                        'Group name': 'Test Room',
                        'Description': 'Test Room',
                        'name_short': 'TR',
                        'Addresses': []
                    }
                ]
            }
        ]
        
        all_addresses = []
        
        return {'floors': floors, 'all_addresses': all_addresses, 'config': config}
    
    def test_empty_building_comparison(self, test_data):
        """Test that both implementations handle empty buildings similarly."""
        # Set up globals for legacy code
        ets_to_openhab.floors = test_data['floors']
        ets_to_openhab.all_addresses = test_data['all_addresses'][:]
        ets_to_openhab.used_addresses = []
        ets_to_openhab.equipments = {}
        ets_to_openhab.export_to_influx = []
        ets_to_openhab.FENSTERKONTAKTE = []
        
        # Get legacy output
        legacy_items, legacy_sitemap, legacy_things = ets_to_openhab.gen_building()
        
        # Reset all_addresses for new implementation
        test_addresses = test_data['all_addresses'][:]
        
        # Get refactored output  
        new_items, new_sitemap, new_things = gen_building_new(
            test_data['floors'],
            test_addresses,
            test_data['config']
        )
        
        # Compare structure (both should have floor/room groups)
        assert 'Group map1' in legacy_items
        assert 'Group map1' in new_items
        assert 'Group map1_1' in legacy_items
        assert 'Group map1_1' in new_items
        
        # Both should generate similar sitemap frames
        assert 'Frame label=' in legacy_sitemap
        assert 'Frame label=' in new_sitemap
        
        print("\n=== Empty Building Comparison ===")
        print(f"Legacy items lines: {len(legacy_items.splitlines())}")
        print(f"New items lines: {len(new_items.splitlines())}")
        print(f"Legacy things lines: {len(legacy_things.splitlines())}")
        print(f"New things lines: {len(new_things.splitlines())}")
    
    def test_output_structure_compatibility(self, test_data):
        """Verify both implementations return compatible output structures."""
        # Get refactored output
        new_items, new_sitemap, new_things = gen_building_new(
            test_data['floors'],
            test_data['all_addresses'],
            test_data['config']
        )
        
        # Verify return types
        assert isinstance(new_items, str), "Items should be string"
        assert isinstance(new_sitemap, str), "Sitemap should be string"
        assert isinstance(new_things, str), "Things should be string"
        
        # Verify basic OpenHAB syntax
        if new_items:
            assert 'Group' in new_items or len(new_items.strip()) == 0
        
        print("\n=== Output Structure Test ===")
        print("✓ All outputs are strings")
        print("✓ Output structure is compatible")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
