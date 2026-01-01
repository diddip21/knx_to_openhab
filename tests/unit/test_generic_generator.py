"""Unit tests for GenericGenerator."""

import unittest
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.generators.generic_generator import GenericGenerator


class TestGenericGenerator(unittest.TestCase):
    def setUp(self):
        self.config = {
            'datapoint_mappings': {
                'DPST-9-1': {'ga_prefix': '9.001', 'item_type': 'Number:Temperature',
                             'semantic_info': '["Measurement", "Temperature"]',
                             'item_icon': 'temperature', 'metadata': ''},
                'DPST-1-19': {'ga_prefix': '1.019', 'item_type': 'Contact',
                              'semantic_info': '["Window"]', 'item_icon': 'window',
                              'metadata': ''},
                'DPST-5-1': {'ga_prefix': 'position=5.001', 'item_type': 'Dimmer',
                             'semantic_info': '["Light"]', 'item_icon': 'light',
                             'metadata': ''}
            },
            'homekit_enabled': False,
            'alexa_enabled': False,
            'defines': {}
        }
        self.all_addresses = [
            {'Address': '1/2/3', 'Name': 'Room_Temp', 'Group name': 'Room_Temp',
             'DatapointType': 'DPST-9-1'},
            {'Address': '1/2/4', 'Name': 'Window_Contact', 'Group name': 'Window_Contact',
             'DatapointType': 'DPST-1-19'},
            {'Address': '1/2/5', 'Name': 'Room_Light', 'Group name': 'Room_Light',
             'DatapointType': 'DPST-5-1'}
        ]
        self.generator = GenericGenerator(self.config, self.all_addresses)
    
    def test_can_handle_mapped_datapoint(self):
        self.assertTrue(self.generator.can_handle({'DatapointType': 'DPST-9-1'}))
        self.assertTrue(self.generator.can_handle({'DatapointType': 'DPST-1-19'}))
    
    def test_cannot_handle_unmapped_datapoint(self):
        self.assertFalse(self.generator.can_handle({'DatapointType': 'DPST-99-99'}))
    
    def test_generate_temperature(self):
        result = self.generator.generate(self.all_addresses[0])
        self.assertIsNotNone(result)
        self.assertEqual(result['item_type'], 'Number:Temperature')
        self.assertIn('9.001', result['thing_info'])
        self.assertIn('temperature', result['item_icon'])
    
    def test_generate_window_contact(self):
        result = self.generator.generate(self.all_addresses[1])
        self.assertIsNotNone(result)
        self.assertEqual(result['item_type'], 'Contact')
        self.assertEqual(result['equipment'], 'Window')
    
    def test_generate_with_position_prefix(self):
        result = self.generator.generate(self.all_addresses[2])
        self.assertIsNotNone(result)
        self.assertIn('position="5.001', result['thing_info'])
    
    def test_generate_unmapped_returns_none(self):
        address = {'Address': '9/9/9', 'DatapointType': 'DPST-99-99', 'Group name': 'Test'}
        result = self.generator.generate(address)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
