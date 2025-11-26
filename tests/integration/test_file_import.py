import sys
import os
import pytest
import json
from pathlib import Path
from xknxproject.xknxproj import XKNXProj

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import knxproject_to_openhab
from config import config

# Define path to tests directory
TESTS_DIR = Path(__file__).parent.parent

def get_json_files():
    """Get all .json files in the tests directory that look like project dumps."""
    return sorted(list(TESTS_DIR.glob("*.json")))

def get_knxproj_files():
    """Get all .knxproj files in the tests directory."""
    return sorted(list(TESTS_DIR.glob("*.knxproj")))

class TestFileImport:
    
    def setup_method(self):
        # Ensure config is initialized
        if 'general' not in config:
             config['general'] = {}
        # Set defaults to avoid errors
        config['general']['FloorNameAsItIs'] = False
        config['general']['RoomNameAsItIs'] = False
        config['general']['item_Floor_nameshort_prefix'] = '='
        config['general']['item_Room_nameshort_prefix'] = '+'
        config['general']['addMissingItems'] = True
        config['general']['unknown_floorname'] = 'unknown'
        config['general']['unknown_roomname'] = 'unknown'
        
        # Update module level vars
        knxproject_to_openhab.FloorNameAsItIs = False
        knxproject_to_openhab.RoomNameAsItIs = False
        knxproject_to_openhab.ITEM_FLOOR_NAME_SHORT_PREFIX = '='
        knxproject_to_openhab.ITEM_ROOM_NAME_SHORT_PREFIX = '+'
        knxproject_to_openhab.ADD_MISSING_ITEMS = True
        knxproject_to_openhab.UNKNOWN_FLOOR_NAME = 'unknown'
        knxproject_to_openhab.UNKNOWN_ROOM_NAME = 'unknown'


    @pytest.mark.parametrize("json_file", get_json_files())
    def test_import_json_dump(self, json_file):
        """Test importing a JSON dump and generating the building structure."""
        print(f"Testing JSON import: {json_file.name}")
        
        with open(json_file, encoding="utf-8") as f:
            project = json.load(f)
            
        # 1. Create Building
        building = knxproject_to_openhab.create_building(project)
        assert building is not None
        assert isinstance(building, list)
        assert len(building) > 0
        
        # Check basic structure of building
        b = building[0]
        assert 'floors' in b
        assert isinstance(b['floors'], list)
        
        # 2. Get Addresses
        # Some JSON dumps might be partial or old, so we wrap in try-except if keys are missing
        try:
            addresses = knxproject_to_openhab.get_addresses(project)
            assert isinstance(addresses, list)
        except KeyError as e:
            pytest.skip(f"Skipping address extraction due to missing key in JSON: {e}")
        except ValueError as e:
             pytest.skip(f"Skipping address extraction due to value error: {e}")

        # 3. Put Addresses in Building
        # This modifies 'building' in place
        try:
            knxproject_to_openhab.put_addresses_in_building(building, addresses, project)
        except Exception as e:
            pytest.fail(f"Failed to put addresses in building: {e}")
            
        # Verify some addresses were placed (optional, depends on file content)
        # We can check if any room has addresses
        total_addresses_placed = 0
        for floor in b['floors']:
            for room in floor['rooms']:
                if 'Addresses' in room:
                    total_addresses_placed += len(room['Addresses'])
        
        print(f"  Placed {total_addresses_placed} addresses in {json_file.name}")


    @pytest.mark.parametrize("knxproj_file", get_knxproj_files())
    def test_import_knxproj(self, knxproj_file):
        """Test importing a .knxproj file."""
        print(f"Testing KNXProj import: {knxproj_file.name}")
        
        # Try without password first
        try:
            knxproj = XKNXProj(path=knxproj_file, password=None, language="de-DE")
            project = knxproj.parse()
        except Exception as e:
            # If it fails (likely password), we skip
            if "password" in str(e).lower() or "encrypted" in str(e).lower():
                pytest.skip(f"Skipping {knxproj_file.name} due to password protection or encryption error: {e}")
            else:
                # Other errors might be parsing issues, which we want to know about
                # But XKNXProj might fail for various reasons on valid files if they are complex
                # For now, let's fail the test to see the error, unless it's a known issue
                pytest.fail(f"Failed to parse {knxproj_file.name}: {e}")

        assert project is not None
        
        # Run the same steps as JSON
        building = knxproject_to_openhab.create_building(project)
        assert building is not None
        
        addresses = knxproject_to_openhab.get_addresses(project)
        assert isinstance(addresses, list)
        
        knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
