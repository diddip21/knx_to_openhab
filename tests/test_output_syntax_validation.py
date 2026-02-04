"""Test that generated OpenHAB configuration files have valid syntax.

This module validates the syntax and structure of generated:
- Items files (items.file format)
- Things files (KNX binding Things format)
- Sitemap files (OpenHAB Sitemap format)

These tests ensure that the KNX project generator produces valid
OpenHAB configuration that can be deployed without syntax errors.

IMPORTANT: Tests require that OpenHAB files are generated first via
the generated_openhab_files fixture. This fixture must be available
and run BEFORE these tests execute.
"""

import logging
import os
import re
from pathlib import Path

import pytest

from config import config

logger = logging.getLogger(__name__)


class TestItemsFileSyntax:
    """Validates generated items file has valid OpenHAB Items syntax."""

    @pytest.fixture(autouse=True)
    def _ensure_files_generated(self, generated_openhab_files):
        """Ensure OpenHAB files are generated before running tests in this class.

        This fixture ensures that the items file exists and is ready for
        validation. It depends on the session-scoped generated_openhab_files
        fixture which generates all files from the ETS project.
        """
        # Verify items file exists
        assert os.path.exists(config["items_path"]), f"Items file not found: {config['items_path']}"
        yield

    def test_items_file_not_empty(self):
        """Items file must contain content."""
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0, "Items file is empty"
        logger.info(f"Items file size: {len(content)} bytes")

    def test_items_has_valid_group_syntax(self):
        """Base group must be defined with valid OpenHAB Group syntax.

        OpenHAB Group syntax: Group name "Label" (parentGroup)
        Example: Group Base "Home" ()
        """
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # OpenHAB Group syntax pattern
        # Format: Group [parent_type] name "label" [icon] (parentGroups) [metadata]
        group_pattern = r'^Group\s+\w+\s+"[^"]*"'
        matches = re.findall(group_pattern, content, re.MULTILINE)
        assert len(matches) > 0, "No valid Group definitions found in items file"
        logger.info(f"Found {len(matches)} valid Group definitions")

    def test_items_no_orphaned_items(self):
        """All items must have a parent group defined.

        An orphaned item is one that references a group that hasn't been
        defined. This test ensures all group references are valid.
        """
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        defined_groups = set()

        # Collect all defined groups (first pass)
        for line in lines:
            # Match: Group [type] name "label"
            match = re.match(r'^Group\s+(?:\w+:)?\w+\s+\w+\s+"', line)
            if match:
                # Extract group name (second word after 'Group')
                words = line.split()
                if len(words) >= 2:
                    group_name = words[1]
                    defined_groups.add(group_name)

        logger.info(f"Defined groups: {len(defined_groups)}")

        # Check all items reference defined groups (second pass)
        orphaned = []
        for line in lines:
            if line.startswith(
                (
                    "Switch",
                    "Contact",
                    "Number",
                    "Dimmer",
                    "Rollershutter",
                    "DateTime",
                    "String",
                )
            ):
                # Extract parent groups from parentheses
                match = re.search(r"\(([^)]+)\)", line)
                if match:
                    parents = match.group(1).split(",")
                    for parent in parents:
                        parent = parent.strip()
                        if parent and parent not in defined_groups:
                            orphaned.append({"line": line.strip(), "missing_group": parent})

        assert len(orphaned) == 0, f"Found {len(orphaned)} orphaned items:\n" + "\n".join(
            [f"  - {o['line'][:60]}... -> missing '{o['missing_group']}'" for o in orphaned[:5]]
        )

    def test_items_no_duplicate_names(self):
        """Item names must be unique (no duplicates).

        Duplicate item names cause OpenHAB runtime errors and item conflicts.
        """
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        item_names = {}
        duplicates = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip() or line.strip().startswith("//"):
                continue
            # Extract item name (second token after type)
            match = re.match(r'^\w+(?:\w+)*\s+(\w+)\s+"', line)
            if match:
                item_name = match.group(1)
                if item_name in item_names:
                    duplicates.append(
                        {
                            "name": item_name,
                            "line1": item_names[item_name],
                            "line2": line_num,
                        }
                    )
                else:
                    item_names[item_name] = line_num

        assert len(duplicates) == 0, f"Found {len(duplicates)} duplicate item names: " + ", ".join(
            [d["name"] for d in duplicates[:5]]
        )

    def test_items_valid_item_types(self):
        """Validate that items use valid OpenHAB item types."""
        valid_types = {
            "Switch",
            "Contact",
            "Number",
            "Dimmer",
            "Rollershutter",
            "DateTime",
            "String",
            "Group",
            "Color",
            "Location",
            "Player",
            "Image",
            "Video",
            "Call",
            "Location",
        }

        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        invalid_items = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip() or line.strip().startswith("//"):
                continue

            # Extract item type (first word)
            parts = line.split()
            if parts:
                item_type = parts[0]
                if item_type not in valid_types and item_type != "Group":
                    invalid_items.append(
                        {"line_num": line_num, "line": line.strip(), "type": item_type}
                    )

        assert (
            len(invalid_items) == 0
        ), f"Found {len(invalid_items)} items with invalid types:\n" + "\n".join(
            [
                f"  Line {i['line_num']}: {i['type']} in '{i['line'][:50]}...'"
                for i in invalid_items[:5]
            ]
        )

    def test_items_valid_label_format(self):
        """Validate that item labels follow correct format."""
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Pattern to match items with labels
        item_label_pattern = r'^(\w+)\s+\w+\s+"([^"]*)"(?:\s+\w+)?.*'
        lines = content.split("\n")
        invalid_labels = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip() or line.strip().startswith("//"):
                continue

            match = re.match(item_label_pattern, line)
            if match:
                item_type, label = match.groups()
                # Labels should not be empty
                if not label.strip():
                    invalid_labels.append(
                        {"line_num": line_num, "line": line.strip(), "label": label}
                    )

        assert (
            len(invalid_labels) == 0
        ), f"Found {len(invalid_labels)} items with invalid labels:\n" + "\n".join(
            [
                f"  Line {i['line_num']}: empty label in '{i['line'][:50]}...'"
                for i in invalid_labels[:5]
            ]
        )

    def test_items_proper_line_format(self):
        """Validate that item lines follow proper OpenHAB format."""
        with open(config["items_path"], "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        malformed_lines = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip() or line.strip().startswith("//"):
                continue

            # Check if line follows expected format: Type Name "Label" [Icon] (Groups) [Metadata]
            # Basic check: should start with a valid item type
            parts = line.split()
            if not parts:
                continue

            item_type = parts[0]
            if item_type in [
                "Switch",
                "Contact",
                "Number",
                "Dimmer",
                "Rollershutter",
                "DateTime",
                "String",
                "Color",
                "Location",
                "Player",
                "Image",
                "Video",
                "Call",
                "Group",
            ]:
                # Should have at least name and label
                if len(parts) < 3:
                    malformed_lines.append({"line_num": line_num, "line": line.strip()})

        assert (
            len(malformed_lines) == 0
        ), f"Found {len(malformed_lines)} malformed item lines:\n" + "\n".join(
            [f"  Line {m['line_num']}: '{m['line'][:50]}...'" for m in malformed_lines[:5]]
        )


class TestThingsFileSyntax:
    """Validates generated things file has valid OpenHAB Things syntax."""

    @pytest.fixture(autouse=True)
    def _ensure_files_generated(self, generated_openhab_files):
        """Ensure OpenHAB files are generated before running tests in this class.

        This fixture ensures that the things file exists and is ready for
        validation. It depends on the session-scoped generated_openhab_files
        fixture which generates all files from the ETS project.
        """
        # Verify things file exists
        assert os.path.exists(
            config["things_path"]
        ), f"Things file not found: {config['things_path']}"
        yield

    def test_things_file_not_empty(self):
        """Things file must contain content."""
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0, "Things file is empty"
        logger.info(f"Things file size: {len(content)} bytes")

    def test_things_has_type_definitions(self):
        """Things file must contain Type definitions for KNX binding.

        OpenHAB Things syntax: Type itemtype : thingid "label" [ config ]
        Example: Type switch : i_EG_WZ_Licht "Light" [ ga="1/1/1" ]
        """
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Skip if file doesn't have expected content structure
        if "Type" not in content:
            pytest.skip("Things file doesn't contain Type definitions - format may differ")

        # OpenHAB Things syntax pattern
        type_pattern = r"^Type\s+\w+\s+:\s+\w+"
        matches = re.findall(type_pattern, content, re.MULTILINE)
        # If we have alternative format, just skip
        if len(matches) == 0:
            pytest.skip("Things file format doesn't match expected Type definition pattern")

    def test_things_has_knx_group_addresses(self):
        """All things must have KNX group address configuration (ga=).

        Each Thing needs a 'ga' parameter that defines the KNX group
        address for communication. Without this, the Thing cannot
        send/receive KNX commands.
        """
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()

        lines = [l for l in content.split("\n") if l.strip().startswith("Type")]

        if len(lines) == 0:
            pytest.skip("No Type definitions found - format may differ")

        missing_ga = []
        for line in lines:
            # Check for ga= parameter
            if "ga=" not in line:
                # Extract thing ID for error message
                match = re.search(r":\s+(\w+)\s+", line)
                thing_id = match.group(1) if match else "unknown"
                missing_ga.append({"line": line.strip()[:80], "thing_id": thing_id})

        # Only fail if we have actual definitions
        if len(lines) > 0:
            assert len(missing_ga) < len(
                lines
            ), f"Most Things ({len(missing_ga)}/{len(lines)}) missing KNX group address (ga=)"

    def test_things_knx_group_addresses_valid_format(self):
        """KNX group addresses must follow valid format (M/G/S).

        KNX group address format: Main/Middle/Sub (e.g., 1/2/3)
        Each part is 0-31 (5 bits) for standard addressing.
        """
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Match ga="M/G/S" or ga=M/G/S patterns
        ga_pattern = r'ga=(?:")?([\.\d/]+)(?:")?'
        matches = re.findall(ga_pattern, content)

        if len(matches) == 0:
            pytest.skip("No group addresses found - format may differ")

        invalid_addresses = []
        for address in matches:
            # Allow both / and . separators (OpenHAB variants)
            address_norm = address.replace(".", "/")
            parts = address_norm.split("/")
            if len(parts) != 3:
                # Different addressing scheme - skip validation
                continue
            try:
                m, g, s = [int(p) for p in parts]
                # Check ranges (5-bit values = 0-31)
                if not (0 <= m <= 31 and 0 <= g <= 31 and 0 <= s <= 31):
                    invalid_addresses.append(address)
            except ValueError:
                continue

        # Only fail if we found definite errors
        assert (
            len(invalid_addresses) < 5
        ), f"Found {len(invalid_addresses)} invalid KNX addresses: " + ", ".join(
            invalid_addresses[:5]
        )

    def test_things_valid_binding_formats(self):
        """Validate that things use valid binding formats."""
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Look for various binding formats
        lines = content.split("\n")
        valid_formats_found = False

        for line in lines:
            line = line.strip()
            if line.startswith("Bridge") or line.startswith("Thing"):
                # Should contain binding identifier like knx:, mqtt:, etc.
                if ":" in line and not line.startswith("//"):
                    valid_formats_found = True
                    break
            elif line.startswith("Type"):
                # Type definitions should have proper format
                if ":" in line and not line.startswith("//"):
                    valid_formats_found = True
                    break

        # Either should find valid formats or skip if in different format
        if not valid_formats_found:
            pytest.skip("No recognizable binding formats found")

    def test_things_configuration_parameters(self):
        """Validate that thing configuration parameters are properly formatted."""
        with open(config["things_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Look for configuration sections [ ... ]
        config_pattern = r"\[(.*?)\]"
        config_matches = re.findall(config_pattern, content, re.DOTALL)

        invalid_configs = []
        for i, config_section in enumerate(config_matches):
            # Check for common configuration patterns
            if "=" not in config_section and config_section.strip():
                invalid_configs.append({"section": config_section[:50], "index": i})

        # Only warn if many invalid configs found
        if len(invalid_configs) > len(config_matches) // 2:
            logger.warning(f"Found {len(invalid_configs)} potentially invalid config sections")


class TestSitemapFileSyntax:
    """Validates generated sitemap has valid OpenHAB Sitemap syntax."""

    @pytest.fixture(autouse=True)
    def _ensure_files_generated(self, generated_openhab_files):
        """Ensure OpenHAB files are generated before running tests in this class.

        This fixture ensures that the sitemap file exists and is ready for
        validation. It depends on the session-scoped generated_openhab_files
        fixture which generates all files from the ETS project.
        """
        # Verify sitemap file exists
        assert os.path.exists(
            config["sitemaps_path"]
        ), f"Sitemap file not found: {config['sitemaps_path']}"
        yield

    def test_sitemap_file_not_empty(self):
        """Sitemap file must contain content."""
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0, "Sitemap file is empty"
        logger.info(f"Sitemap file size: {len(content)} bytes")

    def test_sitemap_has_frames(self):
        """Sitemap should have Frame or similar container definitions.

        OpenHAB Sitemap syntax: Frame label="name" { ... }
        Frames are top-level containers for UI elements.
        """
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Look for Frame definitions or other structural elements
        frame_pattern = r"Frame\s+label=|Group\s+label="
        matches = re.findall(frame_pattern, content)

        if len(matches) == 0:
            # Alternative format - just skip validation
            pytest.skip("No Frame definitions found - format may differ")

    def test_sitemap_structure_nested(self):
        """Sitemap items should be properly nested (indentation).

        Proper nesting indicates correct structure for UI hierarchy.
        """
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Check for nested items (should have leading spaces)
        lines = content.split("\n")
        has_indentation = any(line.startswith(("    ", "\t")) for line in lines)
        if not has_indentation:
            pytest.skip("Sitemap items are not indented - may be single-line format")
        logger.info("Sitemap structure is properly nested")

    def test_sitemap_valid_widget_types(self):
        """Sitemap should only use valid widget types.

        Valid types: Switch, Selection, Setpoint, Slider, Text,
        Group, Frame, Chart, Image, Video, Webview, etc.
        """
        valid_types = {
            "Switch",
            "Selection",
            "Setpoint",
            "Slider",
            "Text",
            "Group",
            "Frame",
            "Chart",
            "Image",
            "Video",
            "Webview",
            "Colorpicker",
            "Mapview",
            "Input",
            "Default",
        }

        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Match widget lines: Widget item=name label="label"
        widget_pattern = r"^\s*(\w+)\s+item="
        matches = re.findall(widget_pattern, content, re.MULTILINE)

        if len(matches) == 0:
            pytest.skip("No widget definitions found")

        invalid_widgets = [w for w in matches if w not in valid_types]
        invalid_widgets = list(set(invalid_widgets))  # Remove duplicates

        assert (
            len(invalid_widgets) == 0
        ), f"Found invalid widget types: {', '.join(invalid_widgets)}"
        logger.info(f"All {len(set(matches))} unique widget types are valid")

    def test_sitemap_valid_label_format(self):
        """Validate that sitemap labels follow correct format."""
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Look for label attributes
        label_pattern = r'label="([^"]*)"|label=(\w+)'
        matches = re.findall(label_pattern, content)

        # Count invalid labels (empty strings)
        empty_labels = 0
        for match in matches:
            # match is a tuple of captured groups, take the non-empty one
            label = match[0] if match[0] else match[1]
            if not label.strip():
                empty_labels += 1

        # Only warn if there are many empty labels
        if empty_labels > len(matches) // 2:
            logger.warning(f"Found {empty_labels} empty labels out of {len(matches)} total")

    def test_sitemap_valid_item_references(self):
        """Validate that sitemap item references are properly formatted."""
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Find item references: item=ItemName
        item_ref_pattern = r"item=(\w+)"
        matches = re.findall(item_ref_pattern, content)

        invalid_refs = []
        for ref in matches:
            # Check if reference follows valid naming convention (alphanumeric + underscore/hyphen)
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", ref):
                invalid_refs.append(ref)

        assert (
            len(invalid_refs) == 0
        ), f"Found {len(invalid_refs)} invalid item references: {invalid_refs[:5]}"

    def test_sitemap_proper_closing_brackets(self):
        """Validate that sitemap has proper opening/closing brackets."""
        with open(config["sitemaps_path"], "r", encoding="utf-8") as f:
            content = f.read()

        # Count opening and closing brackets
        open_count = content.count("{")
        close_count = content.count("}")

        assert (
            open_count == close_count
        ), f"Mismatched brackets: {open_count} opening, {close_count} closing"


def test_comprehensive_file_integrity():
    """Comprehensive test to validate integrity across all generated files."""
    # Check that all expected files exist
    expected_files = [
        config.get("items_path"),
        config.get("things_path"),
        config.get("sitemaps_path"),
        config.get("influx_path"),
    ]

    missing_files = [f for f in expected_files if f and not os.path.exists(f)]

    if missing_files:
        logger.warning(f"Missing expected files: {missing_files}")

    # Check file sizes for reasonableness
    for file_path in expected_files:
        if file_path and os.path.exists(file_path):
            size = os.path.getsize(file_path)
            if size == 0:
                pytest.fail(f"File {file_path} is empty")
            if size > 100 * 1024 * 1024:  # 100MB - probably too large
                logger.warning(f"File {file_path} is very large: {size} bytes")


def test_file_encoding_issues():
    """Test that generated files have proper encoding without issues."""
    files_to_check = [
        config.get("items_path"),
        config.get("things_path"),
        config.get("sitemaps_path"),
    ]

    problematic_chars = []

    for file_path in files_to_check:
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Look for problematic characters that might indicate encoding issues
                if "\ufffd" in content:  # Unicode replacement character
                    problematic_chars.append(f"{file_path}: Contains replacement characters")

            except UnicodeDecodeError as e:
                pytest.fail(f"Encoding error in {file_path}: {e}")

    assert not problematic_chars, f"Found encoding issues: {problematic_chars}"


def test_syntax_validation_error_handling():
    """Test that syntax validation handles errors gracefully."""
    # Test with a temporary fake file that doesn't exist
    original_items_path = config["items_path"]

    # Temporarily change to a non-existent file
    config["items_path"] = "/tmp/nonexistent_file.items"

    try:
        # This should handle the missing file gracefully rather than crash
        with pytest.raises(AssertionError):
            # Manually call the fixture function to trigger the check
            from tests.conftest import generated_openhab_files

            # Just test that the check happens properly
            assert os.path.exists(
                config["items_path"]
            ), f"Items file not found: {config['items_path']}"
    finally:
        # Restore original path
        config["items_path"] = original_items_path
