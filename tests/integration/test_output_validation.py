"""
Output Validation Tests - Golden File Comparison

These tests verify that the OpenHAB file generation produces consistent,
expected output by comparing generated files with reference "Golden Files".
"""

import difflib
import filecmp
import os
import sys
from pathlib import Path

import pytest

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(PROJECT_ROOT)

import ets_to_openhab
import knxproject_to_openhab
from config import config

# Paths
TESTS_DIR = Path(__file__).parent.parent
GOLDEN_CASES = [
    ("Charne", TESTS_DIR / "Charne.knxproj.json"),
    ("UploadJson", TESTS_DIR / "upload.knxprojarchive.json"),
    ("Mini", TESTS_DIR / "fixtures" / "mini_project.json"),
]


class TestOutputValidation:

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

    def _compare_files(self, generated_file, golden_file):
        """Compare two files and return diff if they differ"""
        if not golden_file.exists():
            pytest.skip(f"Golden file not found: {golden_file}")

        if not generated_file.exists():
            pytest.fail(f"Generated file not found: {generated_file}")

        # Read files
        with open(generated_file, "r", encoding="utf-8") as f:
            generated_lines = f.readlines()

        with open(golden_file, "r", encoding="utf-8") as f:
            golden_lines = f.readlines()

        # Compare - fail on any diff to catch behavioral changes
        if generated_lines != golden_lines:
            diff = list(
                difflib.unified_diff(
                    golden_lines,
                    generated_lines,
                    fromfile=f"golden/{golden_file.name}",
                    tofile=f"generated/{generated_file.name}",
                    lineterm="",
                )
            )
            diff_text = "\n".join(diff[:200])
            pytest.fail(
                f"Generated output differs from golden for {golden_file.name} (showing first 200 lines):\n{diff_text}"
            )

    @pytest.mark.parametrize("case_name, project_path", GOLDEN_CASES)
    def test_generate_items_file(
        self, tmp_path, case_name, project_path, generate_output_from_json
    ):
        """Test that generated items file matches golden file"""
        output_dir = generate_output_from_json(project_path, tmp_path)

        generated = output_dir / "knx.items"
        golden = TESTS_DIR / "fixtures" / "expected_output" / case_name / "knx.items"

        self._compare_files(generated, golden)

    @pytest.mark.parametrize("case_name, project_path", GOLDEN_CASES)
    def test_generate_things_file(
        self, tmp_path, case_name, project_path, generate_output_from_json
    ):
        """Test that generated things file matches golden file"""
        output_dir = generate_output_from_json(project_path, tmp_path)

        generated = output_dir / "knx.things"
        golden = TESTS_DIR / "fixtures" / "expected_output" / case_name / "knx.things"

        self._compare_files(generated, golden)

    @pytest.mark.parametrize("case_name, project_path", GOLDEN_CASES)
    def test_generate_sitemap_file(
        self, tmp_path, case_name, project_path, generate_output_from_json
    ):
        """Test that generated sitemap file matches golden file"""
        output_dir = generate_output_from_json(project_path, tmp_path)

        generated = output_dir / "knx.sitemap"
        golden = TESTS_DIR / "fixtures" / "expected_output" / case_name / "knx.sitemap"

        self._compare_files(generated, golden)

    @pytest.mark.parametrize("case_name, project_path", GOLDEN_CASES)
    def test_generate_persistence_file(
        self, tmp_path, case_name, project_path, generate_output_from_json
    ):
        """Test that generated persistence file matches golden file"""
        output_dir = generate_output_from_json(project_path, tmp_path)

        generated = output_dir / "influxdb.persist"
        golden = TESTS_DIR / "fixtures" / "expected_output" / case_name / "influxdb.persist"

        self._compare_files(generated, golden)

    @pytest.mark.parametrize("case_name, project_path", GOLDEN_CASES)
    def test_all_files_generated(
        self, tmp_path, case_name, project_path, generate_output_from_json
    ):
        """Test that all expected files are generated"""
        output_dir = generate_output_from_json(project_path, tmp_path)

        expected_files = ["knx.items", "knx.things", "knx.sitemap", "influxdb.persist"]

        for filename in expected_files:
            file_path = output_dir / filename
            assert file_path.exists(), f"Expected file not generated: {filename}"
            assert file_path.stat().st_size > 0, f"Generated file is empty: {filename}"


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
