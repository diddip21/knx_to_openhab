import os
import re

import pytest
from playwright.sync_api import Page, expect

# Path to a real KNX project file for testing
TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


def test_upload_knx_project(page: Page, base_url, flask_server):
    """Test the full flow of uploading a KNX project."""
    # Skip if test file doesn't exist
    if not os.path.exists(TEST_FILE_PATH):
        pytest.skip(f"Test file not found: {TEST_FILE_PATH}")

    page.goto(base_url)
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")

    # 1. Locate file input
    file_input = page.locator("#fileInput")
    expect(file_input).to_be_visible()

    # 2. Upload file
    file_input.set_input_files(TEST_FILE_PATH)

    # 3. Ensure app script is loaded
    page.wait_for_function("document.readyState === 'complete'")

    # 4. Submit
    submit_btn = page.locator("button[type='submit']")
    submit_btn.click()

    # 5. Verify upload started/finished
    # The UI shows status in #status div
    status_div = page.locator("#status")
    expect(status_div).to_be_visible()
    expect(status_div).not_to_be_empty(timeout=20000)

    # Wait for the UI to confirm the upload/job creation and show details
    expect(status_div).to_contain_text(
        re.compile(r"Processing started|File uploaded, job started"),
        timeout=20000,
    )

    # Job details section should become visible once a job is created
    expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

    # Status badge should indicate job state
    expect(page.locator("#jobDetail .badge")).to_contain_text(
        re.compile(r"running|completed|failed", re.IGNORECASE),
        timeout=20000,
    )


def test_upload_invalid_file_is_rejected_by_backend(page: Page, base_url, flask_server, tmp_path):
    """Test uploading an invalid file type."""
    page.goto(base_url)
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")

    dummy_file = tmp_path / "invalid.txt"
    dummy_file.write_text("not a KNX project", encoding="utf-8")
    file_input = page.locator("#fileInput")
    expect(file_input).to_be_visible()
    file_input.set_input_files(str(dummy_file))

    with page.expect_response(
        lambda response: response.url.endswith("/api/upload") and response.request.method == "POST"
    ) as upload_response:
        page.locator("button[type='submit']").click()

    assert upload_response.value.status == 400
    expect(page.locator("#status")).to_contain_text(
        re.compile(r"not supported|not allowed|invalid", re.IGNORECASE), timeout=10000
    )
