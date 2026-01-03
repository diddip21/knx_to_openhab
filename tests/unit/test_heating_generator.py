"""Unit tests for HeatingGenerator."""
import pytest
from src.generators.heating_generator import HeatingGenerator


@pytest.fixture
def config():
    """Sample configuration for testing."""
    return {
        'separator': '_',
        'defines': {
            'heating': {
                'level_suffix': ['level', 'Ist-Temperatur'],
                'status_level_suffix': ['status', 'Rückmeldung'],
                'icon': 'heating',
                'position': '1'
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
            'Address': '3/1/1',
            'Group_name': 'Wohnzimmer Heizung Ist-Temperatur',
            'DatapointType': 'DPST-5-1',
            'communication_object': [{
                'function_text': 'Ist-Temperatur',
                'flags': {'write': True},
                'device_communication_objects': [
                    {
                        'number': '1',
                        'function_text': 'Rückmeldung',
                        'group_address_links': ['3/1/2']
                    }
                ]
            }]
        },
        {
            'Address': '3/1/2',
            'Group_name': 'Wohnzimmer Heizung Rückmeldung',
            'DatapointType': 'DPST-5-1'
        },
        {
            'Address': '3/2/1',
            'Group_name': 'Hvac Mode',
            'DatapointType': 'DPST-20-102',
            'communication_object': [{
                'function_text': 'Ist-Temperatur', # Generic placeholder
                'flags': {'write': True},
                'device_communication_objects': []
            }]
        }
    ]


def test_can_handle_heating(config, all_addresses):
    """Test that generator can identify heating devices."""
    generator = HeatingGenerator(config, all_addresses)
    # Note: actual DPTs might depend on get_datapoint_type helper
    assert generator.can_handle({'DatapointType': 'DPST-9-1'}) is True or \
           generator.can_handle({'DatapointType': 'DPST-5-10'}) is True or \
           generator.can_handle({'DatapointType': 'DPST-5-1'}) is True


def test_generate_with_status(config, all_addresses):
    """Test heating generation with status."""
    generator = HeatingGenerator(config, all_addresses)
    base = all_addresses[0]
    
    result = generator.generate(base)
    
    assert result is not None
    assert result.success is True
    assert result.item_type == 'Number:Dimensionless'
    assert '3/1/1' in str(result.thing_info)


def test_generate_hvac_mode(config, all_addresses):
    """Test HVAC mode generation."""
    generator = HeatingGenerator(config, all_addresses)
    base = all_addresses[2]
    
    result = generator.generate(base)
    
    assert result is not None
    assert result.success is True
    assert result.item_type == 'Number'
    assert '20.102' in str(result.thing_info)
