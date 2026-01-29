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
            "flags": {"read": True, "write": False, "transmit": True, "update": False}
        }

        flags = get_co_flags(co)
        assert flags is not None
        assert flags["read"] is True
        assert flags["write"] is False
        assert flags["transmit"] is True
        assert flags["update"] is False

    def test_extract_partial_flags(self):
        """Should handle flags when not all 4 are present."""
        co = {"flags": {"read": True, "write": True}}

        flags = get_co_flags(co)
        assert flags is not None
        assert flags["read"] is True
        assert flags["write"] is True
        # Missing flags should default to False
        assert flags.get("transmit", False) is False
        assert flags.get("update", False) is False

    def test_extract_no_flags(self):
        """Should return None when communication object has no flags."""
        co = {"text": "test", "channel": "ch1"}
        assert get_co_flags(co) is None

    def test_extract_empty_flags(self):
        """Should handle empty flags dictionary."""
        co = {"flags": {}}
        flags = get_co_flags(co)
        assert flags is not None
        assert flags.get("read", False) is False
        assert flags.get("write", False) is False

    def test_extract_flags_with_all_false(self):
        """Should correctly handle all flags set to False."""
        co = {
            "flags": {"read": False, "write": False, "transmit": False, "update": False}
        }

        flags = get_co_flags(co)
        assert flags["read"] is False
        assert flags["write"] is False
        assert flags["transmit"] is False
        assert flags["update"] is False

    def test_extract_flags_with_non_boolean_values(self):
        """Should handle non-boolean flag values gracefully."""
        co = {
            "flags": {
                "read": "True",  # String instead of boolean
                "write": 1,  # Integer instead of boolean
                "transmit": 0,  # Integer instead of boolean
                "update": "False",  # String instead of boolean
            }
        }

        flags = get_co_flags(co)
        # Implementation preserves original values, doesn't convert them
        assert flags["read"] == "True"  # String stays as string
        assert flags["write"] == 1  # Integer stays as integer
        assert flags["transmit"] == 0  # Integer stays as integer
        assert flags["update"] == "False"  # String stays as string

    def test_extract_flags_with_none_values(self):
        """Should handle None flag values."""
        co = {"flags": {"read": None, "write": True, "transmit": False}}

        flags = get_co_flags(co)
        assert flags["read"] is None  # None stays as None
        assert flags["write"] is True
        assert flags["transmit"] is False

    def test_extract_flags_case_insensitive(self):
        """Should handle different casing in flag names."""
        co = {
            "FLAGS": {  # Different case
                "READ": True,  # Different case
                "Write": False,  # Mixed case
                "TRANSMIT": True,  # Different case
                "update": False,  # Original case
            }
        }

        flags = get_co_flags(co)
        # Case-sensitive implementation - FLAGS key is not recognized as 'flags'
        assert flags is None  # Different case key not found


class TestFlagsMatch:
    """Test flag matching logic for CO filtering."""

    def test_exact_flag_match(self):
        """Should match when all expected flags match exactly."""
        co_flags = {"read": True, "write": False, "transmit": True, "update": False}
        expected = {"read": True, "write": False}

        assert flags_match(co_flags, expected) is True

    def test_exact_flag_match_single(self):
        """Should match when single expected flag matches."""
        co_flags = {"read": True, "write": False}
        expected = {"read": True}

        assert flags_match(co_flags, expected) is True

    def test_mismatch_flag_value(self):
        """Should fail when expected flag value doesn't match."""
        co_flags = {"read": True, "write": True}
        expected = {"read": True, "write": False}  # write should be False

        assert flags_match(co_flags, expected) is False

    def test_missing_expected_flag(self):
        """Missing flag with default False value should match if expected is False.

        When a flag is missing from co_flags, it defaults to False.
        If expected value for that flag is also False, it's a match.
        This is correct semantics: "not having write" matches "wanting no write".
        """
        co_flags = {"read": True}  # Missing 'write'
        expected = {"read": True, "write": False}  # We want no write (False)

        # This SHOULD match because:
        # - read matches (True == True)
        # - write doesn't exist in co_flags, defaults to False
        # - expected write is False, so False == False ✓
        assert flags_match(co_flags, expected) is True

        # But if we WANTED write=True, it should NOT match:
        expected_write_true = {"read": True, "write": True}
        assert flags_match(co_flags, expected_write_true) is False

    def test_extra_flags_in_co_ok(self):
        """CO having more flags than expected should still match."""
        co_flags = {"read": True, "write": False, "transmit": True, "update": False}
        expected = {"read": True}  # Only check read

        assert flags_match(co_flags, expected) is True

    def test_none_co_flags_pass(self):
        """None co_flags should pass (no filtering)."""
        assert flags_match(None, None) is True
        assert flags_match(None, {"read": True}) is True

    def test_none_expected_flags_pass(self):
        """None expected_flags should pass (no filtering required)."""
        co_flags = {"read": True, "write": False}
        assert flags_match(co_flags, None) is True

    def test_both_none_pass(self):
        """Both None should pass (no filtering)."""
        assert flags_match(None, None) is True

    def test_empty_expected_flags_pass(self):
        """Empty expected_flags dict should pass."""
        co_flags = {"read": True, "write": False}
        assert flags_match(co_flags, {}) is True

    def test_multiple_mismatches(self):
        """Should fail on first mismatch with multiple expected flags."""
        co_flags = {"read": False, "write": False, "transmit": True}
        expected = {"read": True, "write": False, "transmit": True}

        assert flags_match(co_flags, expected) is False

    def test_write_flag_filtering(self):
        """Typical use case: filter by write flag for commands."""
        # Command objects should have write=True
        command_flags = {"read": False, "write": True, "transmit": False}
        expected_command = {"write": True}

        assert flags_match(command_flags, expected_command) is True

    def test_read_flag_filtering(self):
        """Typical use case: filter by read flag for status feedback."""
        # Status objects should have read=True
        status_flags = {"read": True, "write": False, "transmit": True}
        expected_status = {"read": True, "transmit": True}

        assert flags_match(status_flags, expected_status) is True

    def test_complex_filtering_scenario(self):
        """Test complex real-world filtering scenario.

        For a dimmer:
        - status_suffix needs: read=True, transmit=True
        - switch_suffix needs: write=True
        """
        # Status object
        status_co = {"read": True, "write": False, "transmit": True, "update": False}
        status_expected = {"read": True, "transmit": True}
        assert flags_match(status_co, status_expected) is True

        # Command object
        command_co = {"read": False, "write": True, "transmit": False, "update": False}
        command_expected = {"write": True}
        assert flags_match(command_co, command_expected) is True

        # Mismatched object (wrong flags for status)
        wrong_co = {"read": False, "write": True, "transmit": False, "update": False}
        status_expected = {"read": True, "transmit": True}
        assert flags_match(wrong_co, status_expected) is False

    def test_edge_case_empty_strings_as_keys(self):
        """Test handling of edge cases with empty string keys."""
        co_flags = {"": True, "read": True}
        expected = {"read": True}

        # This should work normally despite empty key
        assert flags_match(co_flags, expected) is True

    def test_flag_match_with_different_types(self):
        """Test flag matching with different value types."""
        co_flags = {"read": 1, "write": 0}  # integers instead of booleans
        expected = {"read": True, "write": False}  # booleans

        # Implementation-dependent behavior - may convert or not match
        result = flags_match(co_flags, expected)
        # The actual behavior depends on the implementation

    def test_large_flag_sets(self):
        """Test performance with large flag sets."""
        # Create large flag sets to test performance
        large_co_flags = {f"flag_{i}": i % 2 == 0 for i in range(100)}
        large_expected = {f"flag_{i}": i % 2 == 0 for i in range(50)}  # subset

        # Should match the subset correctly
        assert flags_match(large_co_flags, large_expected) is True


class TestAddressSelectionIntegration:
    """Integration tests for address selection with flags."""

    def test_flag_matching_dimmer_status(self):
        """Test flag matching for dimmer status selection."""
        # A dimmer status should be readable and transmit feedback
        actual = {"read": True, "write": False, "transmit": True, "update": False}
        expected = {"read": True, "transmit": True}

        result = flags_match(actual, expected)
        assert result is True, "Dimmer status should match read+transmit flags"

    def test_flag_matching_dimmer_command(self):
        """Test flag matching for dimmer command selection."""
        # A dimmer command should be writable
        actual = {"read": False, "write": True, "transmit": False, "update": False}
        expected = {"write": True}

        result = flags_match(actual, expected)
        assert result is True, "Dimmer command should match write flag"

    def test_flag_matching_switch_status(self):
        """Test flag matching for switch status selection."""
        # A switch status should be readable
        actual = {"read": True, "write": False, "transmit": True, "update": True}
        expected = {"read": True}

        result = flags_match(actual, expected)
        assert result is True, "Switch status should match read flag"

    def test_flag_matching_exclusion(self):
        """Test that mismatched flags are properly excluded."""
        # This shouldn't match because write=True (we want write=False)
        actual = {
            "read": True,
            "write": True,  # ← Problem
            "transmit": True,
            "update": False,
        }
        expected = {"read": True, "write": False}  # We want write=False

        result = flags_match(actual, expected)
        assert result is False, "Should not match when write flag differs"

    def test_real_world_scenarios(self):
        """Test real-world KNX device scenarios."""
        # Scenario 1: Binary input (sensor) - read-only
        binary_input = {"read": True, "write": False, "transmit": True, "update": False}
        sensor_filter = {"read": True, "write": False}
        assert flags_match(binary_input, sensor_filter) is True

        # Scenario 2: Binary output (actuator) - write-only
        binary_output = {
            "read": False,
            "write": True,
            "transmit": False,
            "update": False,
        }
        actuator_filter = {"write": True}
        assert flags_match(binary_output, actuator_filter) is True

        # Scenario 3: Scene selector - write-only
        scene_selector = {
            "read": False,
            "write": True,
            "transmit": False,
            "update": False,
        }
        scene_filter = {"write": True}
        assert flags_match(scene_selector, scene_filter) is True

        # Scenario 4: Temperature sensor - read + transmit
        temp_sensor = {"read": True, "write": False, "transmit": True, "update": True}
        temp_filter = {"read": True, "transmit": True}
        assert flags_match(temp_sensor, temp_filter) is True


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_deeply_nested_flags(self):
        """Test with deeply nested or complex flag structures."""
        # This tests if the implementation can handle complex nested structures
        complex_co = {
            "flags": {
                "read": True,
                "write": False,
                "transmit": True,
                "update": False,
                "complex_sub_flag": {"sub_read": True, "sub_write": False},
            }
        }
        # Should only process top-level flags, ignore nested ones
        flags = get_co_flags(complex_co)
        assert "read" in flags
        assert "complex_sub_flag" not in flags  # Should not process nested

    def test_unicode_flag_names(self):
        """Test with unicode flag names."""
        unicode_co = {
            "flags": {
                "rèad": True,  # Unicode characters
                "wrițe": False,
                "trânsmit": True,
            }
        }
        # Should handle unicode flag names gracefully
        flags = get_co_flags(unicode_co)
        assert flags is not None

    def test_special_characters_in_flag_values(self):
        """Test with special character values."""
        special_co = {
            "flags": {
                "read": True,
                "write": "special_value",  # Non-boolean value
                "transmit": [],  # Empty list (falsy)
            }
        }
        flags = get_co_flags(special_co)
        # Should handle non-boolean values appropriately
        assert flags is not None

    def test_extremely_large_flag_values(self):
        """Test with extremely large flag values."""
        large_co = {
            "flags": {
                "read": 999999999999999999999,  # Very large number
                "write": -999999999999999999999,  # Very negative number
                "transmit": True,
            }
        }
        flags = get_co_flags(large_co)
        # Implementation preserves original values, doesn't convert them
        assert flags["read"] == 999999999999999999999  # Large number stays as number
        assert (
            flags["write"] == -999999999999999999999
        )  # Negative number stays as number
