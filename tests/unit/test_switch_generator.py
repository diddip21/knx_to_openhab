"""Unit tests for SwitchGenerator."""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.generators.switch_generator import SwitchGenerator


class TestSwitchGenerator(unittest.TestCase):
    """Test cases for SwitchGenerator."""
    
    def setUp(self):
        self.config = {'separator': '_'}
        self.all_addresses = [
            {'Address': '1/1/1', 'Name': 'Room_Light_switch', 'DatapointType': 'DPST-1-1'},
            {'Address': '1/1/2', 'Name': 'Room_Light_status', 'DatapointType': 'DPST-1-1'}
        ]
        self.generator = SwitchGenerator(self.config, self.all_addresses)
    
    def test_can_handle_switch(self):
        address = {'DatapointType': 'DPST-1-1', 'Name': 'Test_switch'}
        self.assertTrue(self.generator.can_handle(address))
    
    def test_cannot_handle_non_switch(self):
        address = {'DatapointType': 'DPST-5-1', 'Name': 'Test_dimmer'}
        self.assertFalse(self.generator.can_handle(address))
    
    def test_generate_complete_switch(self):
        base = self.all_addresses[0]
        context = {'floor': 'Ground', 'room': 'Room', 'basename': 'Room_Light'}
        result = self.generator.generate(base, context)
        self.assertTrue(result.success)
        self.assertEqual(result.item['type'], 'Switch')


if __name__ == '__main__':
    unittest.main()
