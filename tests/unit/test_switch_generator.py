"""Unit tests for SwitchGenerator."""
import pytest
from src.generators.switch_generator import SwitchGenerator


@pytest.fixture
def config():
    """Sample configuration for testing."""
    return {
        'separator': '_',
        'defines': {
            'switch': {
                'switch_suffix': ['Schalten', 'Schalt'],
                'status_suffix': ['Status', 'Rückmeldung', 'Status Ein/Aus'],
                'icon': 'switch'
            }
        },
        'homekit_enabled': False,
        'alexa_enabled': False
    }


@pytest.fixture
def all_addresses():
    """List of all addresses."""
    return [
        {
            'Address': '1/1/1',
            'Group_name': 'Wohnzimmer Licht Schalten',
            'DatapointType': 'DPST-1-1',
            'communication_object': [{
                'function_text': 'Schalten',
                'flags': {'write': True},
                'device_communication_objects': [
                    {
                        'number': '1',
                        'function_text': 'Status Ein/Aus',
                        'group_address_links': ['1/1/2']
                    }
                ]
            }]
        },
        {
            'Address': '1/1/2',
            'Group_name': 'Wohnzimmer Licht Status',
            'DatapointType': 'DPST-1-1'
        }
    ]


def test_can_handle_switch(config, all_addresses):
    """Test that generator can identify switch devices."""
    generator = SwitchGenerator(config, all_addresses)
    address = {'DatapointType': 'DPST-1-1', 'Group_name': 'Test switch'}
    assert generator.can_handle(address) is True


def test_cannot_handle_non_switch(config, all_addresses):
    """Test that generator rejects non-switch devices."""
    generator = SwitchGenerator(config, all_addresses)
    address = {'DatapointType': 'DPST-5-1', 'Group_name': 'Test dimmer'}
    assert generator.can_handle(address) is False


def test_generate_complete_switch(config, all_addresses):
    """Test generation with status address."""
    generator = SwitchGenerator(config, all_addresses)
    base = all_addresses[0]
    context = {'floor': 'Ground', 'room': 'Room', 'item_name': 'Room_Light'}
    
    result = generator.generate(base, context)
    
    # Assert result structure and success
    assert result is not None
    assert result.success is True
    assert result.item_type == 'Switch'
    assert result.semantic_info == '["Switch"]'
    assert '1/1/1' in result.thing_info
    assert '1/1/2' in result.thing_info


def test_generate_incomplete_switch(config):
    """Test generation with missing status."""
    address = {
        'Address': '1/1/3',
        'Group_name': 'Test Schalten',
        'DatapointType': 'DPST-1-1',
        'communication_object': []
    }
    generator = SwitchGenerator(config, [address])
    
    result = generator.generate(address)
    
    # Should still generate basic switch without status or be unsuccessful
    # depending on business requirements. Assuming success=True for basic switch.
    assert result is not None
    assert result.success is True
    assert '1/1/3' in result.thing_info
    assert '1/1/2' not in result.thing_info
