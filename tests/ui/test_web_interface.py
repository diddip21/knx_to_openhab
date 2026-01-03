"""UI tests for the knx_to_openhab web interface using Playwright."""

import pytest
from playwright.sync_api import Page, expect
import re
import os


# DEFAULT CREDENTIALS
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "logihome"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for testing."""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


@pytest.fixture
def test_page(page: Page, base_url):
    """Provide an authenticated page session using Basic Auth."""
    # Backend uses Basic Auth. Playwright supports this in the URL.
    auth_url = base_url.replace("://", f"://{DEFAULT_USERNAME}:{DEFAULT_PASSWORD}@")
    page.goto(auth_url)
    page.wait_for_load_state("networkidle")
    return page


class TestAuthentication:
    """Test authentication and initial page load."""
    
    def test_page_loads(self, page: Page, base_url):
        """Test that the main page loads correctly with credentials."""
        auth_url = base_url.replace("://", f"://{DEFAULT_USERNAME}:{DEFAULT_PASSWORD}@")
        page.goto(auth_url)
        # Playwright expect().to_have_title() requires string or regex
        expect(page).to_have_title(re.compile(r"knx.*openhab", re.IGNORECASE))
        # Verify main heading is visible
        expect(page.locator("h1")).to_be_visible()
        # Use regex to handle potential special characters like arrows or variations
        expect(page.locator("h1")).to_contain_text(re.compile(r"KNX.*OpenHAB", re.IGNORECASE))


class TestProjectUpload:
    """Test project upload section elements."""
    
    def test_upload_interface_elements(self, test_page: Page):
        """Test that all upload interface elements are present."""
        page = test_page
        
        # File input should be present
        expect(page.locator("input[type='file']")).to_be_visible()
        
        # Upload button check - button with type submit
        expect(page.locator("button[type='submit']")).to_be_visible()


class TestSettings:
    """Test settings and configuration section."""
    
    def test_settings_section_exists(self, test_page: Page):
        """Test that settings section is present."""
        page = test_page
        expect(page.locator("#settings-section")).to_be_visible()
        
    def test_expanding_settings(self, test_page: Page):
        """Test that settings section can be expanded and contains new fields."""
        page = test_page
        
        # Initially content might be hidden
        settings_content = page.locator("#settings-content")
        
        # Click header to expand
        page.click(".card-header:has-text('Configuration Settings')")
        expect(settings_content).to_be_visible()
        
        # Check for newly added fields
        expect(page.locator("#conf-floor-prefix")).to_be_visible()


class TestGeneration:
    """Test OpenHAB configuration generation indicators."""
    
    def test_status_messages_containers(self, test_page: Page):
        """Test that status message containers are present."""
        page = test_page
        # Status messages are in specific divs
        expect(page.locator("#configStatus")).to_be_hidden() 
        expect(page.locator("#uploadStatus")).to_be_hidden() # Selector might be different, but assuming standard convention or verified in code?
        # Actually in code it is <div id="status" class="status-message"></div> inside #upload-section
        expect(page.locator("#status")).to_be_visible() # It's empty but the div exists and is visible (block)


class TestResponsiveness:
    """Test layout responsiveness."""
    
    @pytest.mark.parametrize("viewport", [
        {"width": 1920, "height": 1080},  # Desktop
        {"width": 1024, "height": 768},   # Tablet
        {"width": 375, "height": 667},    # Mobile
    ])
    def test_responsive_layout(self, page: Page, base_url, viewport):
        """Test that UI works on different screen sizes."""
        page.set_viewport_size(viewport)
        auth_url = base_url.replace("://", f"://{DEFAULT_USERNAME}:{DEFAULT_PASSWORD}@")
        page.goto(auth_url)
        
        # Page should load successfully
        expect(page).to_have_url(re.compile(f"{re.escape(base_url)}.*"))
        
        # Navbar or main container should be present
        # Based on index.html: <div class="container"> <div class="header-container">
        expect(page.locator(".header-container")).to_be_visible()


class TestVersionCheck:
    """Test version information display."""
    
    def test_version_info_present(self, test_page: Page):
        """Test that version information is displayed."""
        page = test_page
        # Use verified class from index.html
        version_loc = page.locator(".version-badge")
        expect(version_loc).to_be_visible()
        expect(version_loc).to_contain_text(re.compile(r"Version:", re.IGNORECASE))
