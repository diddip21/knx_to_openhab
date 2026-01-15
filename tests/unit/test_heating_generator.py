"""Unit tests for HeatingGenerator."""

import unittest
from unittest.mock import Mock, patch
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.generators.heating_generator import HeatingGenerator


class TestHeatingGenerator(unittest.TestCase):
    def setUp(self):
        self.config = {
            'defines': {'heating': {'level_suffix': 'level', 'status_level_suffix': 'status'}},
            'homekit_enabled': False, 'alexa_enabled': False
        }
        self.all_addresses = [
            {'Address': '3/1/1', 'Name': 'Room_Heating_level', 'Group name': 'Room_Heating',
             'DatapointType': 'DPST-5-010', 'Function': 'Heating'},
            {'Address': '3/1/2', 'Name': 'Room_Heating_status', 'Group name': 'Room_Heating',
             'DatapointType': 'DPST-5-010', 'Function': 'Heating'},
            {'Address': '3/2/1', 'Name': 'Room_Mode', 'Group name': 'Room_Mode',
             'DatapointType': 'DPST-20-102', 'Function': 'Heating'}
        ]
        with patch('src.generators.heating_generator.get_datapoint_type') as mock:
            mock.side_effect = lambda x: f'DPST-{x}'
            self.generator = HeatingGenerator(self.config, self.all_addresses)
    
    @patch('src.generators.heating_generator.get_datapoint_type')
    def test_can_handle_heating(self, mock_type):
        mock_type.side_effect = lambda x: 'DPST-5-010' if x == 'heating' else 'DPST-20-102'
        self.assertTrue(self.generator.can_handle({'DatapointType': 'DPST-5-010'}))
    
    @patch.object(HeatingGenerator, 'get_co_by_functiontext')
    @patch.object(HeatingGenerator, 'get_address_from_dco_enhanced')
    def test_generate_with_status(self, mock_addr, mock_co):
        mock_co.return_value = {'address': '3/1/1'}
        mock_addr.return_value = self.all_addresses[1]
        result = self.generator.generate(self.all_addresses[0])
        self.assertIsNotNone(result)
        self.assertEqual(result['item_type'], 'Number:Dimensionless')
        self.assertIn('5.010', result['thing_info'])
    
    @patch.object(HeatingGenerator, 'get_co_by_functiontext')
    def test_generate_hvac_mode(self, mock_co):
        mock_co.return_value = {'address': '3/2/1'}
        result = self.generator.generate(self.all_addresses[2])
        self.assertIsNotNone(result)
        self.assertEqual(result['item_type'], 'Number')
        self.assertIn('20.102', result['thing_info'])


if __name__ == '__main__':
    unittest.main()
