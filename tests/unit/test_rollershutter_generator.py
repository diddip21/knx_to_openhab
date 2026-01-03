"""Unit tests for RollershutterGenerator."""
import pytest
from src.generators.rollershutter_generator import RollershutterGenerator


@pytest.fixture
def config():
    """Sample configuration for testing."""
    return {
        'separator': '_',
        'prefixes': {'status': 'status', 'moving': 'moving'},
        'defines': {
            'rollershutter': {
                'up_down_suffix': ['up/down', 'Auf/Ab'],
                'stop_suffix': ['stop', 'Stopp'],
                'position_suffix': ['position', 'Position'],
                'position_dpts': ['DPST-5-1'],
                'icon': 'rollershutter'
            }
        }
    }


@pytest.fixture
def all_addresses():
    """List of all addresses."""
    return [
        {
            'Address': '1/2/3',
            'Group_name': 'Livingroom Blinds Auf/Ab',
            'DatapointType': 'DPST-1-8',
            'Function': 'Blind',
            'communication_object': [{
                'function_text': 'Auf/Ab',
                'flags': {'write': True},
                'device_communication_objects': [
                    {
                        'number': '4',
                        'function_text': 'Stopp',
                        'group_address_links': ['1/2/4']
                    },
                    {
                        'number': '5',
                        'function_text': 'Position',
                        'dpts': [{'main': 5, 'sub': 1}],
                        'group_address_links': ['1/2/5']
                    }
                ]
            }]
        },
        {
            'Address': '1/2/4',
            'Group_name': 'Livingroom Blinds Stopp',
            'DatapointType': 'DPST-1-8'
        },
        {
            'Address': '1/2/5',
            'Group_name': 'Livingroom Blinds Position',
            'DatapointType': 'DPST-5-1'
        }
    ]


def test_can_handle_rollershutter(config, all_addresses):
    """Test that generator can identify rollershutter devices."""
    generator = RollershutterGenerator(config, all_addresses)
    from utils import get_datapoint_type
    address = {
        'DatapointType': get_datapoint_type('rollershutter'),
        'Group_name': 'Room Blinds Auf/Ab'
    }
    assert generator.can_handle(address) is True


def test_cannot_handle_non_rollershutter(config, all_addresses):
    """Test that generator rejects non-rollershutter devices."""
    generator = RollershutterGenerator(config, all_addresses)
    address = {
        'DatapointType': 'DPST-1-1',
        'Group_name': 'Room Light'
    }
    assert generator.can_handle(address) is False


def test_generate_complete_rollershutter(config, all_addresses):
    """Test generation with all required addresses."""
    generator = RollershutterGenerator(config, all_addresses)
    base_address = all_addresses[0]
    context = {
        'floor': 'Ground Floor',
        'room': 'Livingroom',
        'item_name': 'Livingroom_Blinds'
    }
    
    result = generator.generate(base_address, context)
    
    # We expect DeviceGeneratorResult even if current code returns Dict
    # because that's the intended API
    assert result is not None
    assert result.success is True
    assert result.item_type == 'Rollershutter'


def test_generate_incomplete_rollershutter(config, all_addresses):
    """Test generation with missing addresses."""
    incomplete_address = {
        'Address': '9/9/9',
        'Group_name': 'Test Blind Auf/Ab',
        'DatapointType': 'DPST-1-8',
        'communication_object': [] # No links
    }
    generator = RollershutterGenerator(config, [incomplete_address])
    
    result = generator.generate(incomplete_address)
    
    # Intended behavior for incomplete devices
    assert result is None or (result is not None and result.success is False)


def test_find_related_addresses(config, all_addresses):
    """Test finding related control addresses."""
    generator = RollershutterGenerator(config, all_addresses)
    base = all_addresses[0]
    define = config['defines']['rollershutter']
    
    # Should find stop address
    stop = generator.find_related_address(
        base['communication_object'][0], 'stop_suffix', define
    )
    assert stop is not None
    assert stop['Address'] == '1/2/4'


def test_position_support(config, all_addresses):
    """Test detection of position feedback support."""
    generator = RollershutterGenerator(config, all_addresses)
    base = all_addresses[0]
    define = config['defines']['rollershutter']
    
    # Should find position address
    position = generator.find_related_address(
        base['communication_object'][0], 'position_suffix', define
    )
    assert position is not None
    assert position['Address'] == '1/2/5'
    assert position['DatapointType'] == 'DPST-5-1'
