"""Unit tests for SceneGenerator class"""
import pytest
from src.generators.scene_generator import SceneGenerator


@pytest.fixture
def sample_config():
    """Sample config for testing"""
    return {
        'defines': {
            'scene': {
                'icon': 'scene',
                'groups': ['Scenes']
            }
        }
    }


@pytest.fixture
def all_addresses():
    """Sample addresses for testing"""
    return []


@pytest.fixture
def scene_generator(sample_config, all_addresses):
    """Create SceneGenerator instance"""
    return SceneGenerator(sample_config, all_addresses)


def test_can_handle_scene(scene_generator):
    """Test that generator recognizes scene addresses"""
    scene_address = {'DatapointType': 'DPST-18-1'}
    assert scene_generator.can_handle(scene_address)


def test_cannot_handle_non_scene(scene_generator):
    """Test that generator rejects non-scene addresses"""
    non_scene_address = {'DatapointType': 'DPST-1-1'}
    assert not scene_generator.can_handle(non_scene_address)


def test_generate_scene(scene_generator):
    """Test scene generation"""
    address = {
        'DatapointType': 'DPST-18-1',
        'Group_name': 'Test Scene',
        'Address': '1/2/3'
    }
    context = {
        'floor_nr': 0,
        'room_nr': 0,
        'floor_name': 'Ground Floor',
        'room_name': 'Living Room',
        'item_name': 'Test_Scene'
    }
    
    result = scene_generator.generate(address, context)
    
    assert result is not None
    assert result.item_type == 'Number'
    assert result.item_name == 'Test_Scene'
    assert result.label == 'Test Scene'
    assert result.icon == 'scene'
    assert 'control' in result.thing_info


def test_generate_scene_without_context(scene_generator):
    """Test scene generation without context"""
    address = {
        'DatapointType': 'DPST-18-1',
        'Group_name': 'Test Scene',
        'Address': '1/2/3'
    }
    context = {}
    
    result = scene_generator.generate(address, context)
    
    assert result is not None
    assert result.item_type == 'Number'
