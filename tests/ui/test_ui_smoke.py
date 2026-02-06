"""Smoke tests for Web UI.

These tests verify basic UI functionality without deep interaction:
- Page loads correctly
- Critical UI elements are present
- Basic navigation works
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
def test_homepage_loads(page: Page, flask_server):
    """Test that the homepage loads successfully."""
    page.goto(flask_server)

    # Check that page loaded (title should be present)
    expect(page).to_have_title("KNX → OpenHAB Generator")


@pytest.mark.ui
def test_upload_form_present(page: Page, flask_server):
    """Test that the upload form is visible on the homepage."""
    page.goto(flask_server)

    # Wait for page to be fully loaded
    page.wait_for_load_state("networkidle")

    # Check for file upload input
    file_input = page.locator('input[type="file"]')
    expect(file_input).to_be_visible()

    # Check for optional password field
    password_input = page.locator('input[type="password"], input[name="password"]')
    # Password field should exist (even if hidden initially)
    expect(password_input).to_be_attached()


@pytest.mark.ui
def test_navigation_elements(page: Page, flask_server):
    """Test that key navigation elements are present."""
    page.goto(flask_server)
    page.wait_for_load_state("networkidle")

    # Check for main container
    main_content = page.locator('.container')
    expect(main_content).to_be_attached()


@pytest.mark.ui
def test_api_status_endpoint(page: Page, flask_server):
    """Test that the API status endpoint returns valid data."""
    # This is a hybrid test: uses Playwright page but tests API
    response = page.request.get(f"{flask_server}/api/status")

    assert response.ok, f"Status endpoint failed with {response.status}"
    data = response.json()
    assert "version" in data or "status" in data, (
        "Status response missing expected fields"
    )


@pytest.mark.ui
@pytest.mark.slow
def test_job_list_page_accessible(page: Page, flask_server):
    """Test that jobs list is accessible (even if empty)."""
    page.goto(flask_server)
    page.wait_for_load_state("networkidle")

    # Try to find a jobs link or section
    # This might be on the same page or a different route
    # Adjust based on actual UI structure
    jobs_section = page.locator('[data-testid="jobs-list"], .jobs-list, #jobs')

    # If jobs section exists on homepage, check it
    if jobs_section.is_visible():
        expect(jobs_section).to_be_visible()
    # Otherwise, check if we can navigate to /api/jobs
    else:
        response = page.request.get(f"{flask_server}/api/jobs")
        assert response.ok, "Jobs API endpoint not accessible"
