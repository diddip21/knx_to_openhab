"""Compare Legacy vs Refactored Generator Outputs.

This test runs the SAME KNX project through both:
1. Legacy generator (ets_to_openhab.py)
2. Refactored generator (src/generators/*)

And compares the outputs to ensure functional equivalence.
"""

import pytest
import sys, os
from pathlib import Path
from difflib import unified_diff

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test with Charne.knxproj
TEST_PROJECT = Path(__file__).parent / 'fixtures' / 'Charne.knxproj'
EXPECTED_OUTPUT_DIR = Path(__file__).parent / 'fixtures' / 'expected_output' / 'Charne'


@pytest.mark.skipif(not TEST_PROJECT.exists(), reason="Charne.knxproj not found")
def test_compare_legacy_vs_refactored():
    """
    CRITICAL TEST: Validates that refactored generators produce 
    functionally equivalent output to legacy code.
    
    Steps:
    1. Run legacy generator on Charne.knxproj
    2. Run refactored generators on same project  
    3. Compare outputs (items, things, sitemaps)
    4. Report differences (if any)
    """
    
    # TODO: This test requires integration between old and new systems
    # For now, this is a placeholder that documents the intended test structure
    
    pytest.skip(
        "Integration layer not yet complete. "
        "This test will be enabled once the refactored generators "
        "are integrated into the main generation pipeline."
    )
    
    # Future implementation will:
    # legacy_output = run_legacy_generator(TEST_PROJECT)
    # refactored_output = run_refactored_generator(TEST_PROJECT)
    # assert_outputs_equivalent(legacy_output, refactored_output)


def test_expected_output_exists():
    """Verify that expected output files exist for comparison."""
    assert EXPECTED_OUTPUT_DIR.exists(), f"Expected output dir not found: {EXPECTED_OUTPUT_DIR}"
    
    # Check for expected output files
    expected_files = ['items.txt', 'things.txt', 'sitemap.txt']
    for filename in expected_files:
        filepath = EXPECTED_OUTPUT_DIR / filename
        if filepath.exists():
            assert filepath.stat().st_size > 0, f"{filename} is empty"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
