"""Integration tests for core business logic of project generation.

These tests verify that:
- Address selection is correct based on flags and DPT filtering
- Device communication objects are properly matched
- KNX addresses are assigned to correct rooms/floors
"""

import pytest
import os
import sys
from unittest.mock import Mock, MagicMock, patch

# Add src directory to path for package imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))

from knx_to_openhab import knxproject
from knx_to_openhab.config import config


class TestAddressPlacementLogic:
    """Test that addresses are correctly placed in building structure."""

    def test_address_placement_with_valid_floor_room(self):
        """Address with valid Floor and Room should be placed correctly."""
        building = [
            {
                'name_long': 'Test Building',
                'floors': [
                    {
                        'name_short': 'EG',
                        'rooms': [
                            {
                                'name_short': 'WZ',
                                'Addresses': []
                            }
                        ]
                    }
                ]
            }
        ]

        address = {
            'Address': '1/1/1',
            'Floor': 'EG',
            'Room': 'WZ',
            'Group name': 'Wohnzimmer | Licht'
        }

        result = knxproject.place_address_in_building(building, address, [])
        assert result is True, "Valid address should be placed"
        assert address in building[0]['floors'][0]['rooms'][0]['Addresses'], \
            "Address should be in room's address list"

    def test_address_placement_unknown_floor(self):
        """Address with unknown floor should not be placed."""
        building = [
            {
                'name_long': 'Test Building',
                'floors': [
                    {
                        'name_short': 'EG',
                        'rooms': []
                    }
                ]
            }
        ]

        address = {
            'Address': '1/1/1',
            'Floor': 'UNKNOWN',  # Invalid floor
            'Room': 'WZ',
            'Group name': 'Test'
        }

        result = knxproject.place_address_in_building(building, address, [])
        assert result is False, "Address with unknown floor should not be placed"

    def test_address_placement_unknown_room(self):
        """Address with unknown room should not be placed."""
        building = [
            {
                'name_long': 'Test Building',
                'floors': [
                    {
                        'name_short': 'EG',
                        'rooms': [
                            {'name_short': 'WZ', 'Addresses': []}
                        ]
                    }
                ]
            }
        ]

        address = {
            'Address': '1/1/1',
            'Floor': 'EG',
            'Room': 'UNKNOWN',  # Invalid room
            'Group name': 'Test'
        }

        result = knxproject.place_address_in_building(building, address, [])
        assert result is False, "Address with unknown room should not be placed"


class TestDeviceCommunicationObjectMatching:
    """Test that device communication objects are properly matched."""

    def test_extract_communication_objects_with_device_cos(self):
        """Should extract communication objects with device_communication_objects."""
        # Mock data
        communication_objects = {
            'co1': {
                'id': 'co1',
                'device_address': 'device1',
                'flags': {'read': True, 'write': False},
                'device_communication_objects': [
                    {'id': 'dco1', 'channel': 'ch1'}
                ]
            }
        }
        devices = {
            'device1': {
                'id': 'device1',
                'communication_object_ids': ['co1']
            }
        }
        address = {
            'communication_object_ids': ['co1']
        }

        result = knxproject.extract_communication_objects(address, communication_objects, devices)
        assert len(result) > 0, "Should extract communication objects"
        assert result[0]['device_communication_objects'] is not None


class TestAddressPlacementByDevice:
    """Test address placement based on device association."""

    def test_address_by_device_placement(self):
        """Address should be placed in room with associated device."""
        building = [
            {
                'name_long': 'Test Building',
                'floors': [
                    {
                        'name_short': 'EG',
                        'rooms': [
                            {
                                'name_short': 'WZ',
                                'devices': ['device1'],
                                'Addresses': []
                            }
                        ]
                    }
                ]
            }
        ]

        read_co = {
            'device_address': 'device1',
            'id': 'co1'
        }

        address = {
            'Address': '1/1/1',
            'Group name': 'Wohnzimmer | Licht'
        }

        addresses = [address]

        result = knxproject.place_address_by_device(building, address, read_co, addresses)
        assert result is True, "Address should be placed by device association"


class TestAddressDatapointTypeHandling:
    """Test that addresses are correctly typed by datapoint."""

    def test_format_datapoint_type_with_sub(self):
        """Should format datapoint with sub-type as DPST."""
        address = {
            'dpt': {'main': 5, 'sub': 1}
        }
        result = knxproject.format_datapoint_type(address)
        assert result == 'DPST-5-1', f"Expected 'DPST-5-1', got '{result}'"

    def test_format_datapoint_type_no_sub(self):
        """Should format datapoint without sub-type as DPT."""
        address = {
            'dpt': {'main': 1, 'sub': None}
        }
        result = knxproject.format_datapoint_type(address)
        assert result == 'DPT-1', f"Expected 'DPT-1', got '{result}'"


class TestBuildingCreation:
    """Test building structure creation from project data."""

    def test_create_building_basic(self):
        """Should create basic building structure with floors and rooms."""
        # Mock KNX project structure
        project = {
            'locations': {
                'loc1': {
                    'type': 'Building',
                    'name': 'Haus 1',
                    'description': 'Main House',
                    'spaces': {
                        'floor1': {
                            'type': 'Floor',
                            'name': 'Erdgeschoss',
                            'description': 'Ground Floor',
                            'devices': [],
                            'spaces': {
                                'room1': {
                                    'type': 'Room',
                                    'name': 'Wohnzimmer',
                                    'description': 'Living Room',
                                    'usage_text': 'Living',
                                    'devices': [],
                                    'spaces': {}
                                }
                            }
                        }
                    }
                }
            }
        }

        result = knxproject.create_building(project)
        assert len(result) == 1, "Should create one building"
        assert len(result[0]['floors']) >= 1, "Building should have floors"
        assert len(result[0]['floors'][0]['rooms']) >= 1, "Floor should have rooms"
