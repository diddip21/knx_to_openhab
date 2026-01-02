"""Integration test validating business logic for refactored generators.

This test ensures that the refactored generator architecture produces functionally
correct output that meets business requirements, even if the internal structure differs
from the legacy implementation.
"""
import pytest
import json
from pathlib import Path
from src.generators.dimmer_generator import DimmerGenerator
from src.generators.scene_generator import SceneGenerator


@pytest.fixture
def config():
    """Load real config from config.json"""
    config_path = Path(__file__).parent.parent.parent / 'config.json'
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    # Minimal fallback config
    return {
        'defines': {
            'dimmer': {
                'status_suffix': ['Status Dimmwert'],
                'status_dpts': ['DPST-5-1'],
                'icon': 'light'
            },
            'scene': {
                'dpts': ['DPST-18-1']
            }
        },
        'homekit_enabled': False
    }


def test_dimmer_generator_business_requirements(config):
    """Test that dimmer generator meets core business requirements."""
    # Sample dimmer with status
    dimmer_addr = {
        'Address': '1/1/1',
        'Group_name': 'Living Room Light',
        'DatapointType': 'DPST-5-1',
        'communication_object': [{
            'device_communication_objects': [{
                'function_text': 'Status Dimmwert',
                'dpts': [{'main': 5, 'sub': 1}],
                'flags': {'read': True, 'transmit': True},
                'group_address_links': ['1/1/2']
            }]
        }]
    }
    
    status_addr = {
        'Address': '1/1/2',
        'Group_name': 'Living Room Light Status',
        'DatapointType': 'DPST-5-1'
    }
    
    generator = DimmerGenerator(config, [dimmer_addr, status_addr])
    
    # Business requirement 1: Can identify dimmer addresses
    assert generator.can_handle(dimmer_addr), "Should identify dimmer by DPT"
    
    # Business requirement 2: Generates valid configuration
    result = generator.generate(dimmer_addr)
    
    assert result is not None, "Should generate config for valid dimmer"
    assert result.success, "Generation should succeed"
    
    # Business requirement 3: Proper device classification
    assert result.item_type == 'Dimmer', "Should set correct item type"
    assert result.equipment == 'Lightbulb', "Should classify as Lightbulb"
    
    # Business requirement 4: Contains necessary KNX addresses
    assert result.used_addresses, "Should track used addresses"
    assert '1/1/1' in result.used_addresses, "Should include control address"


def test_scene_generator_business_requirements(config):
    """Test that scene generator meets core business requirements."""
    scene_addr = {
        'Address': '2/1/1',
        'Group_name': 'Living Room Scene 1',
        'DatapointType': 'DPST-18-1'
    }
    
    generator = SceneGenerator(config, [scene_addr])
    
    # Business requirement 1: Can identify scene addresses
    assert generator.can_handle(scene_addr), "Should identify scene by DPT"
    
    # Business requirement 2: Generates valid configuration  
    result = generator.generate(scene_addr)
    
    assert result is not None, "Should generate config for scene"
    assert result.success, "Generation should succeed"


def test_generator_isolation(config):
    """Test that generators correctly isolate their functionality."""
    dimmer_addr = {'Address': '1/1/1', 'DatapointType': 'DPST-5-1'}
    scene_addr = {'Address': '2/1/1', 'DatapointType': 'DPST-18-1'}
    
    all_addrs = [dimmer_addr, scene_addr]
    
    dimmer_gen = DimmerGenerator(config, all_addrs)
    scene_gen = SceneGenerator(config, all_addrs)
    
    # Business requirement: Generators only handle their device types
    assert dimmer_gen.can_handle(dimmer_addr), "Dimmer gen handles dimmer"
    assert not dimmer_gen.can_handle(scene_addr), "Dimmer gen rejects scene"
    
    assert scene_gen.can_handle(scene_addr), "Scene gen handles scene"
    assert not scene_gen.can_handle(dimmer_addr), "Scene gen rejects dimmer"


def test_refactored_api_consistency(config):
    """Test that new API is consistent across generators."""
    dimmer_addr = {'Address': '1/1/1', 'DatapointType': 'DPST-5-1',
                   'communication_object': [{'device_communication_objects': []}]}
    
    generator = DimmerGenerator(config, [dimmer_addr])
    result = generator.generate(dimmer_addr)
    
    # Business requirement: Consistent result structure
    assert hasattr(result, 'success'), "Result has success field"
    assert hasattr(result, 'used_addresses'), "Result has used_addresses field"
    assert hasattr(result, 'item_type'), "Result has item_type field"
    assert hasattr(result, 'metadata'), "Result has metadata field"
    
    # Business requirement: Dict-style access for compatibility
    assert result['success'] == result.success, "Dict access matches attribute"
    assert 'success' in result, "'in' operator works"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
