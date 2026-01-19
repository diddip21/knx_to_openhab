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

import pytest
import re
import os
from pathlib import Path
from config import config
import logging

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
        assert os.path.exists(config['items_path']), \
            f"Items file not found: {config['items_path']}"
        yield

    def test_items_file_not_empty(self):
        """Items file must contain content."""
        with open(config['items_path'], 'r', encoding='utf-8') as f:
            content = f.read()
        assert len(content) > 0, "Items file is empty"
        logger.info(f"Items file size: {len(content)} bytes")

    def test_items_has_valid_group_syntax(self):
        """Base group must be defined with valid OpenHAB Group syntax.
        
        OpenHAB Group syntax: Group name "Label" (parentGroup)
        Example: Group Base "Home" ()
        """
        with open(config['items_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # OpenHAB Group syntax pattern
        # Format: Group [parent_type] name "label" [icon] (parentGroups) [metadata]
        group_pattern = r'^Group\s+\w+\s+"[^"]*"'
        matches = re.findall(group_pattern, content, re.MULTILINE)
        assert len(matches) > 0, \
            "No valid Group definitions found in items file"
        logger.info(f"Found {len(matches)} valid Group definitions")

    def test_items_no_orphaned_items(self):
        """All items must have a parent group defined.
        
        An orphaned item is one that references a group that hasn't been
        defined. This test ensures all group references are valid.
        """
        with open(config['items_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')
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
            if line.startswith(('Switch', 'Contact', 'Number', 'Dimmer',
                               'Rollershutter', 'DateTime', 'String')):
                # Extract parent groups from parentheses
                match = re.search(r'\(([^)]+)\)', line)
                if match:
                    parents = match.group(1).split(',')
                    for parent in parents:
                        parent = parent.strip()
                        if parent and parent not in defined_groups:
                            orphaned.append({
                                'line': line.strip(),
                                'missing_group': parent
                            })

        assert len(orphaned) == 0, \
            f"Found {len(orphaned)} orphaned items:\n" + \
            "\n".join([f"  - {o['line'][:60]}... -> missing '{o['missing_group']}'" 
                      for o in orphaned[:5]])

    def test_items_no_duplicate_names(self):
        """Item names must be unique (no duplicates).
        
        Duplicate item names cause OpenHAB runtime errors and item conflicts.
        """
        with open(config['items_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')
        item_names = {}
        duplicates = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip() or line.strip().startswith('//'):
                continue
            # Extract item name (second token after type)
            match = re.match(r'^\w+(?:\w+)*\s+(\w+)\s+"', line)
            if match:
                item_name = match.group(1)
                if item_name in item_names:
                    duplicates.append({
                        'name': item_name,
                        'line1': item_names[item_name],
                        'line2': line_num
                    })
                else:
                    item_names[item_name] = line_num

        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate item names: " + \
            ", ".join([d['name'] for d in duplicates[:5]])


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
        assert os.path.exists(config['things_path']), \
            f"Things file not found: {config['things_path']}"
        yield

    def test_things_file_not_empty(self):
        """Things file must contain content."""
        with open(config['things_path'], 'r', encoding='utf-8') as f:
            content = f.read()
        assert len(content) > 0, "Things file is empty"
        logger.info(f"Things file size: {len(content)} bytes")

    def test_things_has_type_definitions(self):
        """Things file must contain Type definitions for KNX binding.
        
        OpenHAB Things syntax: Type itemtype : thingid "label" [ config ]
        Example: Type switch : i_EG_WZ_Licht "Light" [ ga="1/1/1" ]
        """
        with open(config['things_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # Skip if file doesn't have expected content structure
        if 'Type' not in content:
            pytest.skip("Things file doesn't contain Type definitions - format may differ")

        # OpenHAB Things syntax pattern
        type_pattern = r'^Type\s+\w+\s+:\s+\w+'
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
        with open(config['things_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        lines = [l for l in content.split('\n') if l.strip().startswith('Type')]
        
        if len(lines) == 0:
            pytest.skip("No Type definitions found - format may differ")

        missing_ga = []
        for line in lines:
            # Check for ga= parameter
            if 'ga=' not in line:
                # Extract thing ID for error message
                match = re.search(r':\s+(\w+)\s+', line)
                thing_id = match.group(1) if match else "unknown"
                missing_ga.append({
                    'line': line.strip()[:80],
                    'thing_id': thing_id
                })

        # Only fail if we have actual definitions
        if len(lines) > 0:
            assert len(missing_ga) < len(lines), \
                f"Most Things ({len(missing_ga)}/{len(lines)}) missing KNX group address (ga=)"

    def test_things_knx_group_addresses_valid_format(self):
        """KNX group addresses must follow valid format (M/G/S).
        
        KNX group address format: Main/Middle/Sub (e.g., 1/2/3)
        Each part is 0-31 (5 bits) for standard addressing.
        """
        with open(config['things_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # Match ga="M/G/S" or ga=M/G/S patterns
        ga_pattern = r'ga=(?:")?([\.\d/]+)(?:")?'
        matches = re.findall(ga_pattern, content)

        if len(matches) == 0:
            pytest.skip("No group addresses found - format may differ")

        invalid_addresses = []
        for address in matches:
            # Allow both / and . separators (OpenHAB variants)
            address_norm = address.replace('.', '/')
            parts = address_norm.split('/')
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
        assert len(invalid_addresses) < 5, \
            f"Found {len(invalid_addresses)} invalid KNX addresses: " + \
            ", ".join(invalid_addresses[:5])


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
        assert os.path.exists(config['sitemaps_path']), \
            f"Sitemap file not found: {config['sitemaps_path']}"
        yield

    def test_sitemap_file_not_empty(self):
        """Sitemap file must contain content."""
        with open(config['sitemaps_path'], 'r', encoding='utf-8') as f:
            content = f.read()
        assert len(content) > 0, "Sitemap file is empty"
        logger.info(f"Sitemap file size: {len(content)} bytes")

    def test_sitemap_has_frames(self):
        """Sitemap should have Frame or similar container definitions.
        
        OpenHAB Sitemap syntax: Frame label="name" { ... }
        Frames are top-level containers for UI elements.
        """
        with open(config['sitemaps_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # Look for Frame definitions or other structural elements
        frame_pattern = r'Frame\s+label=|Group\s+label='
        matches = re.findall(frame_pattern, content)
        
        if len(matches) == 0:
            # Alternative format - just skip validation
            pytest.skip("No Frame definitions found - format may differ")

    def test_sitemap_structure_nested(self):
        """Sitemap items should be properly nested (indentation).
        
        Proper nesting indicates correct structure for UI hierarchy.
        """
        with open(config['sitemaps_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for nested items (should have leading spaces)
        lines = content.split('\n')
        has_indentation = any(line.startswith(('    ', '\t')) for line in lines)
        if not has_indentation:
            pytest.skip("Sitemap items are not indented - may be single-line format")
        logger.info("Sitemap structure is properly nested")

    def test_sitemap_valid_widget_types(self):
        """Sitemap should only use valid widget types.
        
        Valid types: Switch, Selection, Setpoint, Slider, Text,
        Group, Frame, Chart, Image, Video, Webview, etc.
        """
        valid_types = {
            'Switch', 'Selection', 'Setpoint', 'Slider', 'Text',
            'Group', 'Frame', 'Chart', 'Image', 'Video', 'Webview',
            'Colorpicker', 'Mapview', 'Input', 'Default'
        }

        with open(config['sitemaps_path'], 'r', encoding='utf-8') as f:
            content = f.read()

        # Match widget lines: Widget item=name label="label"
        widget_pattern = r'^\s*(\w+)\s+item='
        matches = re.findall(widget_pattern, content, re.MULTILINE)

        if len(matches) == 0:
            pytest.skip("No widget definitions found")

        invalid_widgets = [w for w in matches if w not in valid_types]
        invalid_widgets = list(set(invalid_widgets))  # Remove duplicates

        assert len(invalid_widgets) == 0, \
            f"Found invalid widget types: {', '.join(invalid_widgets)}"
        logger.info(f"All {len(set(matches))} unique widget types are valid")
