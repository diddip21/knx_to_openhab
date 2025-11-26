import sys
import os
import pytest

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import knxproject_to_openhab
from config import config

class TestKnxParsing:
    
    def setup_method(self):
        # Reset config flags for each test
        # We need to modify the global config object that knxproject_to_openhab uses
        # Since knxproject_to_openhab imports 'config' from 'config', and 'config' is a dict in config.py
        # We can modify it here.
        
        # Ensure 'general' exists (it should from real config)
        if 'general' not in config:
            config['general'] = {}
            
        config['general']['FloorNameAsItIs'] = False
        config['general']['RoomNameAsItIs'] = False
        config['general']['item_Floor_nameshort_prefix'] = '='
        config['general']['item_Room_nameshort_prefix'] = '+'
        
        # Also update module-level variables in knxproject_to_openhab if they are copies
        # Looking at knxproject_to_openhab.py:
        # FloorNameAsItIs = config['general']['FloorNameAsItIs']
        # These are assigned at module level, so changing config dict won't change them!
        # We must update the module attributes directly.
        knxproject_to_openhab.FloorNameAsItIs = False
        knxproject_to_openhab.RoomNameAsItIs = False
        knxproject_to_openhab.ITEM_FLOOR_NAME_SHORT_PREFIX = '='
        knxproject_to_openhab.ITEM_ROOM_NAME_SHORT_PREFIX = '+'

    def test_find_floors_nested(self):
        """Test finding floors in a nested structure (Building -> Floor -> Room)."""
        spaces = {
            'building1': {
                'type': 'Building',
                'spaces': {
                    'floor1': {
                        'type': 'Floor',
                        'name': 'Ground Floor',
                        'spaces': {}
                    }
                }
            }
        }
        floors = knxproject_to_openhab.find_floors(spaces)
        assert len(floors) == 1
        assert floors[0]['name'] == 'Ground Floor'

    def test_find_floors_direct_rooms(self):
        """Test finding floors when Building contains Rooms directly."""
        spaces = {
            'building1': {
                'type': 'Building',
                'name': 'Main Building',
                'spaces': {
                    'room1': {
                        'type': 'Room',
                        'name': 'Living Room'
                    }
                }
            }
        }
        floors = knxproject_to_openhab.find_floors(spaces)
        assert len(floors) == 1
        assert floors[0]['name'] == 'Main Building'

    def test_find_floors_empty(self):
        """Test finding floors with empty spaces."""
        floors = knxproject_to_openhab.find_floors({})
        assert floors == []

    def test_get_floor_name_regex_match(self):
        """Test extracting short floor name using regex."""
        floor = {'name': 'EG Ground Floor', 'description': ''}
        # Assuming regex matches 'EG'
        short, long_name, plain = knxproject_to_openhab.get_floor_name(floor)
        # With real config, regex might be different.
        # Config: "item_Floor_nameshort": "^=?[a-zA-Z]{1,5}\\b"
        # 'EG' matches.
        assert short == '=EG' # Prefix added
        assert plain == 'Ground Floor'

    def test_get_floor_name_no_match(self):
        """Test fallback when no short name regex matches."""
        # Regex expects 1-5 chars at start. 
        floor = {'name': 'LongNameFloor', 'description': ''}
        short, long_name, plain = knxproject_to_openhab.get_floor_name(floor)
        assert short == ''

    def test_get_floor_name_as_it_is(self):
        """Test get_floor_name with FloorNameAsItIs=True."""
        knxproject_to_openhab.FloorNameAsItIs = True
        floor = {'name': 'EG Ground Floor', 'description': ''}
        short, long_name, plain = knxproject_to_openhab.get_floor_name(floor)
        assert short == 'EG Ground Floor'
        assert long_name == 'EG Ground Floor'
        assert plain == 'EG Ground Floor'

    def test_get_room_name_with_floor_prefix(self):
        """Test extracting room name that contains floor prefix."""
        # Setup floor data
        floor_data = {'name_short': '=EG', 'name_long': '=EG', 'Description': 'Ground Floor'}
        
        # Room name example: "=EG+RM1 Living Room"
        room = {'name': '=EG+RM1 Living Room', 'usage_text': ''}
        
        short, long_name, plain = knxproject_to_openhab.get_room_name(room, floor_data)
        
        assert short == '+RM1'
        assert plain == 'Living Room'
        assert long_name == '=EG+RM1'

    def test_get_room_name_no_match(self):
        """Test room name generation when no pattern matches."""
        floor_data = {'name_short': '=EG', 'name_long': '=EG'}
        room = {'name': 'Just A Room', 'usage_text': ''}
        
        short, long_name, plain = knxproject_to_openhab.get_room_name(room, floor_data)
        
        # Fallback logic: room_short_name = ITEM_ROOM_NAME_SHORT_PREFIX + 'RMxx'
        assert short == '+RMxx'
        assert 'RMxx' in long_name

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
