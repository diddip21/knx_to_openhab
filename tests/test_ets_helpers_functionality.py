"""Unit tests for ets_helpers module functions.

This module tests the helper functions in ets_helpers.py that handle:
- Communication object flag extraction and matching
- Data point type (DPT) extraction from device communication objects
- Address filtering based on flags and DPT types
"""

import pytest
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ets_helpers import get_co_flags, flags_match, get_dpt_from_dco


class TestGetCoFlags:
    """Test the get_co_flags function."""

    def test_get_co_flags_all_present(self):
        """Test extracting all flag types when all are present."""
        co = {
            'flags': {
                'read': True,
                'write': False,
                'transmit': True,
                'update': False
            }
        }

        flags = get_co_flags(co)
        assert flags is not None
        assert flags['read'] is True
        assert flags['write'] is False
        assert flags['transmit'] is True
        assert flags['update'] is False

    def test_get_co_flags_partial_present(self):
        """Test extracting flags when not all are present."""
        co = {
            'flags': {
                'read': True,
                'write': False
            }
        }

        flags = get_co_flags(co)
        assert flags is not None
        assert flags['read'] is True
        assert flags['write'] is False
        assert flags.get('transmit', False) is False
        assert flags.get('update', False) is False

    def test_get_co_flags_none_when_no_flags_key(self):
        """Test that None is returned when no flags key exists."""
        co = {'text': 'test', 'channel': 'ch1'}
        assert get_co_flags(co) is None

    def test_get_co_flags_none_when_flags_is_none(self):
        """Test that None is returned when flags value is None."""
        co = {'flags': None}
        assert get_co_flags(co) is None

    def test_get_co_flags_empty_flags_dict(self):
        """Test handling of empty flags dictionary."""
        co = {'flags': {}}
        flags = get_co_flags(co)
        assert flags is not None
        assert flags.get('read', False) is False
        assert flags.get('write', False) is False
        assert flags.get('transmit', False) is False
        assert flags.get('update', False) is False

    def test_get_co_flags_all_false(self):
        """Test handling of all flags set to False."""
        co = {
            'flags': {
                'read': False,
                'write': False,
                'transmit': False,
                'update': False
            }
        }

        flags = get_co_flags(co)
        assert flags['read'] is False
        assert flags['write'] is False
        assert flags['transmit'] is False
        assert flags['update'] is False

    def test_get_co_flags_with_non_boolean_values(self):
        """Test handling of non-boolean flag values."""
        co = {
            'flags': {
                'read': 'True',  # String instead of boolean
                'write': 1,      # Integer instead of boolean
                'transmit': 0,   # Integer instead of boolean
                'update': []     # Empty list (falsy)
            }
        }

        flags = get_co_flags(co)
        # Implementation preserves original values, doesn't convert them
        assert flags['read'] == 'True'  # String stays as string
        assert flags['write'] == 1      # Integer stays as integer
        assert flags['transmit'] == 0   # Integer stays as integer
        assert flags['update'] == []    # List stays as list

    def test_get_co_flags_with_none_flag_values(self):
        """Test handling of None flag values."""
        co = {
            'flags': {
                'read': None,
                'write': True,
                'transmit': False
            }
        }

        flags = get_co_flags(co)
        assert flags['read'] is None    # None stays as None
        assert flags['write'] is True
        assert flags['transmit'] is False

    def test_get_co_flags_with_invalid_input(self):
        """Test handling of invalid input types."""
        # Test with non-dict input
        assert get_co_flags("invalid") is None
        assert get_co_flags(123) is None
        assert get_co_flags([]) is None
        assert get_co_flags(None) is None

    def test_get_co_flags_with_invalid_flags_type(self):
        """Test handling of invalid flags value type."""
        co = {'flags': 'not_a_dict'}
        assert get_co_flags(co) is None

        co = {'flags': ['not_a_dict']}
        assert get_co_flags(co) is None


class TestFlagsMatch:
    """Test the flags_match function."""

    def test_flags_match_exact_match(self):
        """Test matching when all expected flags match exactly."""
        co_flags = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': False
        }
        expected = {'read': True, 'write': False}

        assert flags_match(co_flags, expected) is True

    def test_flags_match_single_flag_match(self):
        """Test matching when single expected flag matches."""
        co_flags = {'read': True, 'write': False}
        expected = {'read': True}

        assert flags_match(co_flags, expected) is True

    def test_flags_match_mismatch_value(self):
        """Test that mismatched flag values return False."""
        co_flags = {'read': True, 'write': True}
        expected = {'read': True, 'write': False}  # write should be False

        assert flags_match(co_flags, expected) is False

    def test_flags_match_missing_expected_flag(self):
        """Test that missing CO flags default to False and match if expected is False."""
        co_flags = {'read': True}  # Missing 'write'
        expected = {'read': True, 'write': False}  # We want no write (False)

        # This SHOULD match because:
        # - read matches (True == True)
        # - write doesn't exist in co_flags, defaults to False
        # - expected write is False, so False == False ✓
        assert flags_match(co_flags, expected) is True

        # But if we WANTED write=True, it should NOT match:
        expected_write_true = {'read': True, 'write': True}
        assert flags_match(co_flags, expected_write_true) is False

    def test_flags_match_extra_flags_in_co_ok(self):
        """Test that CO having more flags than expected still matches."""
        co_flags = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': False
        }
        expected = {'read': True}  # Only check read

        assert flags_match(co_flags, expected) is True

    def test_flags_match_none_co_flags_passes(self):
        """Test that None co_flags passes (no filtering)."""
        assert flags_match(None, None) is True
        assert flags_match(None, {'read': True}) is True

    def test_flags_match_none_expected_flags_passes(self):
        """Test that None expected_flags passes (no filtering required)."""
        co_flags = {'read': True, 'write': False}
        assert flags_match(co_flags, None) is True

    def test_flags_match_both_none_pass(self):
        """Test that both None passes (no filtering)."""
        assert flags_match(None, None) is True

    def test_flags_match_empty_expected_flags_pass(self):
        """Test that empty expected_flags dict passes."""
        co_flags = {'read': True, 'write': False}
        assert flags_match(co_flags, {}) is True

    def test_flags_match_multiple_mismatches(self):
        """Test that multiple mismatches return False."""
        co_flags = {'read': False, 'write': False, 'transmit': True}
        expected = {'read': True, 'write': False, 'transmit': True}

        assert flags_match(co_flags, expected) is False

    def test_flags_match_write_flag_filtering(self):
        """Test typical use case: filter by write flag for commands."""
        # Command objects should have write=True
        command_flags = {'read': False, 'write': True, 'transmit': False}
        expected_command = {'write': True}

        assert flags_match(command_flags, expected_command) is True

    def test_flags_match_read_flag_filtering(self):
        """Test typical use case: filter by read flag for status feedback."""
        # Status objects should have read=True
        status_flags = {'read': True, 'write': False, 'transmit': True}
        expected_status = {'read': True, 'transmit': True}

        assert flags_match(status_flags, expected_status) is True

    def test_flags_match_complex_filtering_scenario(self):
        """Test complex real-world filtering scenario."""
        # Status object
        status_co = {'read': True, 'write': False, 'transmit': True, 'update': False}
        status_expected = {'read': True, 'transmit': True}
        assert flags_match(status_co, status_expected) is True

        # Command object
        command_co = {'read': False, 'write': True, 'transmit': False, 'update': False}
        command_expected = {'write': True}
        assert flags_match(command_co, command_expected) is True

        # Mismatched object (wrong flags for status)
        wrong_co = {'read': False, 'write': True, 'transmit': False, 'update': False}
        status_expected = {'read': True, 'transmit': True}
        assert flags_match(wrong_co, status_expected) is False

    def test_flags_match_edge_cases_with_different_types(self):
        """Test edge cases with different value types."""
        # Testing how the function handles truthy/falsy values
        co_flags = {'read': 1, 'write': 0}  # integers instead of booleans
        expected = {'read': True, 'write': False}  # booleans
        
        # The implementation treats truthy/falsy values appropriately
        result = flags_match(co_flags, expected)
        assert result is True  # 1 is truthy (like True), 0 is falsy (like False)


class TestGetDptFromDco:
    """Test the get_dpt_from_dco function."""

    def test_get_dpt_from_dco_valid_dpt(self):
        """Test extracting DPT from valid device communication object."""
        dco = {'dpts': [{'main': 5, 'sub': 1}]}
        result = get_dpt_from_dco(dco)
        assert result == '5.001'

    def test_get_dpt_from_dco_multiple_dpts(self):
        """Test extracting first DPT when multiple are present."""
        dco = {
            'dpts': [
                {'main': 1, 'sub': 2},
                {'main': 5, 'sub': 1}  # Second one should be ignored
            ]
        }
        result = get_dpt_from_dco(dco)
        assert result == '1.002'

    def test_get_dpt_from_dco_three_digit_padding(self):
        """Test that sub-value is properly padded to three digits."""
        dco = {'dpts': [{'main': 1, 'sub': 10}]}
        result = get_dpt_from_dco(dco)
        assert result == '1.010'

        dco = {'dpts': [{'main': 1, 'sub': 100}]}
        result = get_dpt_from_dco(dco)
        assert result == '1.100'

    def test_get_dpt_from_dco_returns_none_when_no_dpts_key(self):
        """Test that None is returned when no dpts key exists."""
        dco = {'text': 'test', 'channel': 'ch1'}
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_returns_none_when_dpts_empty(self):
        """Test that None is returned when dpts array is empty."""
        dco = {'dpts': []}
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_returns_none_when_dpts_not_list(self):
        """Test that None is returned when dpts is not a list."""
        dco = {'dpts': 'not_a_list'}
        assert get_dpt_from_dco(dco) is None

        dco = {'dpts': {'not': 'a_list'}}
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_returns_none_when_first_dpt_not_dict(self):
        """Test that None is returned when first DPT is not a dict."""
        dco = {'dpts': ['not_a_dict']}
        assert get_dpt_from_dco(dco) is None

        dco = {'dpts': [123]}
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_returns_none_when_missing_main_or_sub(self):
        """Test that None is returned when main or sub is missing."""
        dco = {'dpts': [{'main': 5}]}  # Missing 'sub'
        assert get_dpt_from_dco(dco) is None

        dco = {'dpts': [{'sub': 1}]}  # Missing 'main'
        assert get_dpt_from_dco(dco) is None

        dco = {'dpts': [{}]}  # Both missing
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_returns_none_when_main_or_sub_none(self):
        """Test that None is returned when main or sub is None."""
        dco = {'dpts': [{'main': 5, 'sub': None}]}
        assert get_dpt_from_dco(dco) is None

        dco = {'dpts': [{'main': None, 'sub': 1}]}
        assert get_dpt_from_dco(dco) is None

    def test_get_dpt_from_dco_with_negative_values(self):
        """Test handling of negative main/sub values."""
        dco = {'dpts': [{'main': -1, 'sub': -1}]}
        result = get_dpt_from_dco(dco)
        assert result == '-1.-01'  # Negative values with padding

    def test_get_dpt_from_dco_with_zero_values(self):
        """Test handling of zero main/sub values."""
        dco = {'dpts': [{'main': 0, 'sub': 0}]}
        result = get_dpt_from_dco(dco)
        assert result == '0.000'

    def test_get_dpt_from_dco_with_large_values(self):
        """Test handling of large main/sub values."""
        dco = {'dpts': [{'main': 999, 'sub': 999}]}
        result = get_dpt_from_dco(dco)
        assert result == '999.999'

    def test_get_dpt_from_dco_with_invalid_input(self):
        """Test handling of invalid input types."""
        # Test with non-dict input
        assert get_dpt_from_dco("invalid") is None
        assert get_dpt_from_dco(123) is None
        assert get_dpt_from_dco([]) is None
        assert get_dpt_from_dco(None) is None


class TestIntegrationScenarios:
    """Test integration scenarios combining multiple helper functions."""

    def test_complete_flag_processing_workflow(self):
        """Test complete workflow: extract flags, then match them."""
        # Simulate a real communication object
        co = {
            'text': 'Dimmer Status',
            'flags': {
                'read': True,
                'write': False,
                'transmit': True,
                'update': False
            }
        }

        # Extract flags
        flags = get_co_flags(co)
        assert flags is not None

        # Match against expected filters
        # Looking for readable and transmittable objects (status objects)
        expected_status = {'read': True, 'transmit': True}
        assert flags_match(flags, expected_status) is True

        # Should not match command objects (writable)
        expected_command = {'write': True}
        assert flags_match(flags, expected_command) is False

    def test_complete_dpt_processing_workflow(self):
        """Test complete workflow: extract DPT and use it in processing."""
        # Simulate a real device communication object
        dco = {
            'text': 'Temperature Sensor',
            'dpts': [{'main': 9, 'sub': 1}]  # Temperature DPT
        }

        # Extract DPT
        dpt = get_dpt_from_dco(dco)
        assert dpt == '9.001'

        # Verify it's the expected temperature DPT
        assert dpt.startswith('9.')  # Temperature domain

    def test_combined_processing_for_knx_device(self):
        """Test combined processing for a typical KNX device."""
        # Simulate a dimmer device with both command and status objects
        command_co = {
            'text': 'Dimmer Command',
            'flags': {
                'read': False,
                'write': True,
                'transmit': False,
                'update': False
            },
            'dpts': [{'main': 3, 'sub': 7}]  # Dimming control DPT
        }

        status_co = {
            'text': 'Dimmer Status',
            'flags': {
                'read': True,
                'write': False,
                'transmit': True,
                'update': True
            },
            'dpts': [{'main': 5, 'sub': 1}]  # Dimmer position DPT
        }

        # Process command CO
        cmd_flags = get_co_flags(command_co)
        cmd_dpt = get_dpt_from_dco(command_co)
        
        assert cmd_flags is not None
        assert cmd_dpt == '3.007'  # Dimming control
        assert flags_match(cmd_flags, {'write': True}) is True  # Should be writable
        assert flags_match(cmd_flags, {'read': True}) is False  # Should not be readable

        # Process status CO
        status_flags = get_co_flags(status_co)
        status_dpt = get_dpt_from_dco(status_co)
        
        assert status_flags is not None
        assert status_dpt == '5.001'  # Dimmer position
        assert flags_match(status_flags, {'read': True}) is True  # Should be readable
        assert flags_match(status_flags, {'write': True}) is False  # Should not be writable
