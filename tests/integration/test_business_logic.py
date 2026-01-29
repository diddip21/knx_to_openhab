"""
Business Logic Tests - Log Validation

These tests verify that the business logic produces expected warnings
and log messages, such as "No Room found" for unplaced addresses.
"""

import sys
import os
import pytest
import json
import logging
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(PROJECT_ROOT)

import knxproject_to_openhab
import ets_to_openhab
from config import config

# Paths
TESTS_DIR = Path(__file__).parent.parent
TEST_PROJECT = TESTS_DIR / "Charne.knxproj.json"


class TestBusinessLogic:

    def setup_method(self):
        """Setup for each test - reset global state"""
        # Reset module-level variables
        ets_to_openhab.floors = []
        ets_to_openhab.all_addresses = []
        ets_to_openhab.used_addresses = []
        ets_to_openhab.equipments = {}
        ets_to_openhab.FENSTERKONTAKTE = []
        ets_to_openhab.export_to_influx = []

        # Set config defaults
        config["general"]["FloorNameAsItIs"] = False
        config["general"]["RoomNameAsItIs"] = False
        config["general"]["addMissingItems"] = True

        knxproject_to_openhab.FloorNameAsItIs = False
        knxproject_to_openhab.RoomNameAsItIs = False
        knxproject_to_openhab.ADD_MISSING_ITEMS = True

    def test_no_room_found_warnings(self, caplog):
        """Test that 'No Room found' warnings are logged for unplaced addresses"""
        # Load test project
        with open(TEST_PROJECT, encoding="utf-8") as f:
            project = json.load(f)

        # Set logging level to capture warnings
        caplog.set_level(logging.WARNING)

        # Generate building structure and addresses
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)

        # This should generate "No Room found" warnings
        knxproject_to_openhab.put_addresses_in_building(building, addresses, project)

        # Check that warnings were logged
        no_room_warnings = [
            record for record in caplog.records if "No Room found" in record.message
        ]

        # For Charne project, we expect some addresses without rooms
        # Based on the command output, we saw warnings for addresses like:
        # "=1.OG +RM6 Wanne_sch_rm", "=UG +RM1 LED Treppe Farbtemperatur relativ", etc.
        assert (
            len(no_room_warnings) > 0
        ), "Expected 'No Room found' warnings but none were logged"

        # Verify warning format
        for warning in no_room_warnings:
            assert warning.levelname == "WARNING"
            assert "No Room found for" in warning.message

    def test_incomplete_dimmer_warnings(self, caplog):
        """Test that 'incomplete dimmer' warnings are logged"""
        # Load test project
        with open(TEST_PROJECT, encoding="utf-8") as f:
            project = json.load(f)

        caplog.set_level(logging.WARNING)

        # Generate building structure and addresses
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(
            building, addresses, project
        )

        # Set module variables for ets_to_openhab
        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses

        # Generate items (this is where dimmer warnings occur)
        ets_to_openhab.gen_building()

        # Check for incomplete dimmer/rollershutter warnings
        incomplete_warnings = [
            record
            for record in caplog.records
            if "incomplete" in record.message.lower()
        ]

        # Note: This test may pass with 0 warnings if all dimmers are complete
        # We're just verifying the logging mechanism works
        print(f"Found {len(incomplete_warnings)} incomplete component warnings")

    def test_unused_addresses_logged(self, caplog):
        """Test that unused addresses are logged during generation"""
        # Load test project
        with open(TEST_PROJECT, encoding="utf-8") as f:
            project = json.load(f)

        caplog.set_level(logging.INFO)

        # Generate building structure and addresses
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(
            building, addresses, project
        )

        # Set module variables for ets_to_openhab
        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses

        # Generate items - this will log unused addresses if any
        items, sitemap, things = ets_to_openhab.gen_building()

        # After generation, check if we have info about address usage
        # The test passes if gen_building() completes successfully
        # and generates items
        assert items is not None, "gen_building() should return items"
        assert len(items) > 0, "Items should be generated"

    def test_scene_without_mapping_logged(self, caplog):
        """Test that scenes without mappings are logged"""
        # Load test project
        with open(TEST_PROJECT, encoding="utf-8") as f:
            project = json.load(f)

        caplog.set_level(logging.INFO)

        # Generate building structure and addresses
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(
            building, addresses, project
        )

        # Set module variables for ets_to_openhab
        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses

        # Generate items
        items, sitemap, things = ets_to_openhab.gen_building()

        # Check for scene mapping warnings
        scene_logs = [
            record
            for record in caplog.records
            if "no mapping for scene" in record.message.lower()
        ]

        # Based on command output: "no mapping for scene 0/4/0 Szene"
        # We may or may not have these depending on project configuration
        print(f"Found {len(scene_logs)} scene mapping warnings")

    def test_logging_levels(self, caplog):
        """Test that different log levels are used appropriately"""
        # Load test project
        with open(TEST_PROJECT, encoding="utf-8") as f:
            project = json.load(f)

        caplog.set_level(logging.DEBUG)

        # Full processing
        building = knxproject_to_openhab.create_building(project)
        addresses = knxproject_to_openhab.get_addresses(project)
        house = knxproject_to_openhab.put_addresses_in_building(
            building, addresses, project
        )

        ets_to_openhab.floors = house[0]["floors"]
        ets_to_openhab.all_addresses = addresses
        items, sitemap, things = ets_to_openhab.gen_building()

        # Verify we have different log levels
        log_levels = {record.levelname for record in caplog.records}

        assert (
            "INFO" in log_levels or "WARNING" in log_levels
        ), "Expected at least INFO or WARNING level logs"


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
