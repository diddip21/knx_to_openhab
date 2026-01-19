"""Unit tests for core address selection logic from gen_building().

This module tests the flag matching and address filtering functions that are
responsible for correctly mapping KNX datapoints to OpenHAB items based on
configurable flags and datapoint types.
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ets_helpers import get_co_flags, flags_match


class TestCoFlags:
    """Test communication object flag extraction."""

    def test_extract_all_flags_present(self):
        """Should extract all 4 flag types when all are present."""
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

    def test_extract_partial_flags(self):
        """Should handle flags when not all 4 are present."""
        co = {
            'flags': {
                'read': True,
                'write': True
            }
        }

        flags = get_co_flags(co)
        assert flags is not None
        assert flags['read'] is True
        assert flags['write'] is True
        # Missing flags should default to False
        assert flags.get('transmit', False) is False
        assert flags.get('update', False) is False

    def test_extract_no_flags(self):
        """Should return None when communication object has no flags."""
        co = {'text': 'test', 'channel': 'ch1'}
        assert get_co_flags(co) is None

    def test_extract_empty_flags(self):
        """Should handle empty flags dictionary."""
        co = {'flags': {}}
        flags = get_co_flags(co)
        assert flags is not None
        assert flags.get('read', False) is False
        assert flags.get('write', False) is False

    def test_extract_flags_with_all_false(self):
        """Should correctly handle all flags set to False."""
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


class TestFlagsMatch:
    """Test flag matching logic for CO filtering."""

    def test_exact_flag_match(self):
        """Should match when all expected flags match exactly."""
        co_flags = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': False
        }
        expected = {'read': True, 'write': False}

        assert flags_match(co_flags, expected) is True

    def test_exact_flag_match_single(self):
        """Should match when single expected flag matches."""
        co_flags = {'read': True, 'write': False}
        expected = {'read': True}

        assert flags_match(co_flags, expected) is True

    def test_mismatch_flag_value(self):
        """Should fail when expected flag value doesn't match."""
        co_flags = {'read': True, 'write': True}
        expected = {'read': True, 'write': False}  # write should be False

        assert flags_match(co_flags, expected) is False

    def test_missing_expected_flag(self):
        """Should fail when CO is missing expected flag."""
        co_flags = {'read': True}  # Missing 'write'
        expected = {'read': True, 'write': False}

        assert flags_match(co_flags, expected) is False

    def test_extra_flags_in_co_ok(self):
        """CO having more flags than expected should still match."""
        co_flags = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': False
        }
        expected = {'read': True}  # Only check read

        assert flags_match(co_flags, expected) is True

    def test_none_co_flags_pass(self):
        """None co_flags should pass (no filtering)."""
        assert flags_match(None, None) is True
        assert flags_match(None, {'read': True}) is True

    def test_none_expected_flags_pass(self):
        """None expected_flags should pass (no filtering required)."""
        co_flags = {'read': True, 'write': False}
        assert flags_match(co_flags, None) is True

    def test_both_none_pass(self):
        """Both None should pass (no filtering)."""
        assert flags_match(None, None) is True

    def test_empty_expected_flags_pass(self):
        """Empty expected_flags dict should pass."""
        co_flags = {'read': True, 'write': False}
        assert flags_match(co_flags, {}) is True

    def test_multiple_mismatches(self):
        """Should fail on first mismatch with multiple expected flags."""
        co_flags = {'read': False, 'write': False, 'transmit': True}
        expected = {'read': True, 'write': False, 'transmit': True}

        assert flags_match(co_flags, expected) is False

    def test_write_flag_filtering(self):
        """Typical use case: filter by write flag for commands."""
        # Command objects should have write=True
        command_flags = {'read': False, 'write': True, 'transmit': False}
        expected_command = {'write': True}

        assert flags_match(command_flags, expected_command) is True

    def test_read_flag_filtering(self):
        """Typical use case: filter by read flag for status feedback."""
        # Status objects should have read=True
        status_flags = {'read': True, 'write': False, 'transmit': True}
        expected_status = {'read': True, 'transmit': True}

        assert flags_match(status_flags, expected_status) is True

    def test_complex_filtering_scenario(self):
        """Test complex real-world filtering scenario.
        
        For a dimmer:
        - status_suffix needs: read=True, transmit=True
        - switch_suffix needs: write=True
        """
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


class TestAddressSelectionIntegration:
    """Integration tests for address selection with flags."""

    def test_flag_matching_dimmer_status(self):
        """Test flag matching for dimmer status selection."""
        # A dimmer status should be readable and transmit feedback
        actual = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': False
        }
        expected = {'read': True, 'transmit': True}

        result = flags_match(actual, expected)
        assert result is True, "Dimmer status should match read+transmit flags"

    def test_flag_matching_dimmer_command(self):
        """Test flag matching for dimmer command selection."""
        # A dimmer command should be writable
        actual = {
            'read': False,
            'write': True,
            'transmit': False,
            'update': False
        }
        expected = {'write': True}

        result = flags_match(actual, expected)
        assert result is True, "Dimmer command should match write flag"

    def test_flag_matching_switch_status(self):
        """Test flag matching for switch status selection."""
        # A switch status should be readable
        actual = {
            'read': True,
            'write': False,
            'transmit': True,
            'update': True
        }
        expected = {'read': True}

        result = flags_match(actual, expected)
        assert result is True, "Switch status should match read flag"

    def test_flag_matching_exclusion(self):
        """Test that mismatched flags are properly excluded."""
        # This shouldn't match because write=True (we want write=False)
        actual = {
            'read': True,
            'write': True,  # ← Problem
            'transmit': True,
            'update': False
        }
        expected = {'read': True, 'write': False}  # We want write=False

        result = flags_match(actual, expected)
        assert result is False, "Should not match when write flag differs"
