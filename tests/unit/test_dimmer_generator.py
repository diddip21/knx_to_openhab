"""Unit tests for dimmer generator"""

import pytest
from src.generators.dimmer_generator import DimmerGenerator


@pytest.fixture
def config():
    """Sample configuration for testing."""
    return {
        'defines': {
            'dimmer': {
                'absolut_suffix': ['Dimmen absolut', ':(Dimm Wert)'],
                'status_suffix': ['Rückmeldung Dimmen', 'Status Dimmwert'],
                'status_dpts': ['DPST-5-1'],
                'status_flags': {'read': True, 'transmit': True, 'write': False},
                'relativ_suffix': ['Dimmen relativ'],
                'relativ_dpts': ['DPST-3-7'],
                'switch_suffix': ['Schalten'],
                'switch_status_suffix': ['Status Ein/Aus'],
                'drop': []
            }
        },
        'homekit_enabled': False,
        'alexa_enabled': False
    }


@pytest.fixture
def dimmer_address():
    """Sample dimmer address."""
    return {
        'Address': '1/2/3',
        'Group name': 'Wohnzimmer Licht Dimmen absolut',
        'DatapointType': 'DPST-5-1',
        'Description': 'Main light',
        'communication_object': [{
            'function_text': 'Dimmen absolut',
            'flags': {'read': False, 'write': True, 'transmit': False},
            'device_communication_objects': [
                {
                    'number': '1',
                    'function_text': 'Status Dimmwert',
                    'channel': '1',
                    'dpts': [{'main': 5, 'sub': 1}],
                    'flags': {'read': True, 'write': False, 'transmit': True},
                    'group_address_links': ['1/2/4']
                }
            ]
        }]
    }


@pytest.fixture
def status_address():
    """Sample status address."""
    return {
        'Address': '1/2/4',
        'Group name': 'Wohnzimmer Licht Status Dimmwert',
        'DatapointType': 'DPST-5-1'
    }


@pytest.fixture
def all_addresses(dimmer_address, status_address):
    """List of all addresses."""
    return [dimmer_address, status_address]


def test_can_handle_dimmer(config, dimmer_address, all_addresses):
    """Test that generator can handle dimmer addresses."""
    generator = DimmerGenerator(config, all_addresses)
    assert generator.can_handle(dimmer_address) is True


def test_cannot_handle_non_dimmer(config, all_addresses):
    """Test that generator rejects non-dimmer addresses."""
    generator = DimmerGenerator(config, all_addresses)
    switch_address = {'DatapointType': 'DPST-1-1'}
    assert generator.can_handle(switch_address) is False


def test_generate_basic_dimmer(config, dimmer_address, all_addresses):
    """Test basic dimmer generation with status."""
    generator = DimmerGenerator(config, all_addresses)
    result = generator.generate(dimmer_address)
    
    assert result is not None
    assert result['item_type'] == 'Dimmer'
    assert result['equipment'] == 'Lightbulb'
    assert result['semantic_info'] == '["Light"]'
    assert result['item_icon'] == 'light'
    assert 'position=' in result['thing_info']
    assert '1/2/3' in result['thing_info']
    assert '1/2/4' in result['thing_info']  # Status address


def test_generate_incomplete_dimmer(config, all_addresses):
    """Test dimmer without status address returns None."""
    incomplete_dimmer = {
        'Address': '1/2/5',
        'Group name': 'Incomplete Dimmer',
        'DatapointType': 'DPST-5-1',
        'communication_object': [{
            'function_text': 'Dimmen absolut',
            'flags': {'read': False, 'write': True},
            'device_communication_objects': []  # No status!
        }]
    }
    
    generator = DimmerGenerator(config, [incomplete_dimmer])
    result = generator.generate(incomplete_dimmer)
    
    assert result is None


def test_generate_with_homekit(config, dimmer_address, all_addresses):
    """Test dimmer generation with Homekit enabled."""
    config['homekit_enabled'] = True
    generator = DimmerGenerator(config, all_addresses)
    result = generator.generate(dimmer_address)
    
    assert result is not None
    assert 'homekit=' in result['metadata']
    assert 'Lighting' in result['metadata']


def test_mark_address_used(config, dimmer_address, all_addresses):
    """Test that addresses are marked as used."""
    generator = DimmerGenerator(config, all_addresses)
    generator.generate(dimmer_address)
    
    # Status address should be marked as used
    assert generator.is_address_used('1/2/4')
