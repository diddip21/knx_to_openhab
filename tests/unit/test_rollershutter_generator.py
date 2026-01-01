"""Unit tests for RollershutterGenerator."""

import unittest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.generators.rollershutter_generator import RollershutterGenerator


class TestRollershutterGenerator(unittest.TestCase):
    """Test cases for RollershutterGenerator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'separator': '_',
            'prefixes': {'status': 'status', 'moving': 'moving'}
        }
        self.all_addresses = [
            {
                'Address': '1/2/3',
                'Name': 'Livingroom_Blinds_up_down',
                'DatapointType': 'DPST-1-8',  # Up/Down
                'Function': 'Blind'
            },
            {
                'Address': '1/2/4',
                'Name': 'Livingroom_Blinds_stop',
                'DatapointType': 'DPST-1-8',  # Stop
                'Function': 'Blind'
            },
            {
                'Address': '1/2/5',
                'Name': 'Livingroom_Blinds_position',
                'DatapointType': 'DPST-5-1',  # Position 0-100%
                'Function': 'Blind'
            }
        ]
        self.generator = RollershutterGenerator(self.config, self.all_addresses)
    
    def test_can_handle_rollershutter(self):
        """Test that generator can identify rollershutter devices."""
        address = {
            'DatapointType': 'DPST-1-8',
            'Function': 'Blind',
            'Name': 'Room_Blinds_up_down'
        }
        self.assertTrue(self.generator.can_handle(address))
    
    def test_cannot_handle_non_rollershutter(self):
        """Test that generator rejects non-rollershutter devices."""
        address = {
            'DatapointType': 'DPST-1-1',  # Switch
            'Function': 'Light',
            'Name': 'Room_Light'
        }
        self.assertFalse(self.generator.can_handle(address))
    
    def test_generate_complete_rollershutter(self):
        """Test generation with all required addresses."""
        base_address = self.all_addresses[0]
        context = {
            'floor': 'Ground Floor',
            'room': 'Livingroom',
            'basename': 'Livingroom_Blinds'
        }
        
        result = self.generator.generate(base_address, context)
        
        self.assertTrue(result.success)
        self.assertIsNotNone(result.item)
        self.assertEqual(result.item['type'], 'Rollershutter')
        self.assertIn('up_down', result.channels)
        self.assertIsNone(result.error_message)
    
    def test_generate_incomplete_rollershutter(self):
        """Test generation with missing addresses."""
        base_address = {
            'Address': '9/9/9',
            'Name': 'Test_Blind_up_down',
            'DatapointType': 'DPST-1-8',
            'Function': 'Blind'
        }
        context = {
            'floor': 'Test Floor',
            'room': 'Test Room',
            'basename': 'Test_Blind'
        }
        
        result = self.generator.generate(base_address, context)
        
        # Should still generate but with warning
        self.assertTrue(result.success)
        self.assertIsNotNone(result.warnings)
    
    def test_find_related_addresses(self):
        """Test finding related control addresses."""
        base = self.all_addresses[0]
        
        # Should find stop address
        stop = self.generator.find_related_address(
            base, 'stop', self.config['prefixes']
        )
        self.assertIsNotNone(stop)
        self.assertIn('stop', stop['Name'])
    
    def test_position_support(self):
        """Test detection of position feedback support."""
        base = self.all_addresses[0]
        
        # Should find position address
        position = self.generator.find_related_address(
            base, 'position', self.config['prefixes']
        )
        self.assertIsNotNone(position)
        self.assertEqual(position['DatapointType'], 'DPST-5-1')


if __name__ == '__main__':
    unittest.main()
