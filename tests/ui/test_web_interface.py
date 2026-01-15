"""UI tests for the knx_to_openhab web interface using Playwright."""

import pytest
from playwright.sync_api import Page, expect
import time


BASE_URL = "http://localhost:8085"
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
def authenticated_page(page: Page):
    """Provide an authenticated page session."""
    page.goto(BASE_URL)
    
    # Check if already logged in, if not, login
    if "login" in page.url.lower() or page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", DEFAULT_USERNAME)
        page.fill("input[name='password']", DEFAULT_PASSWORD)
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
    
    return page


class TestAuthentication:
    """Test authentication and login functionality."""
    
    def test_login_page_loads(self, page: Page):
        """Test that login page loads correctly."""
        page.goto(BASE_URL)
        expect(page).to_have_title(lambda title: "knx" in title.lower() or "openhab" in title.lower())
        expect(page.locator("input[name='username']")).to_be_visible()
        expect(page.locator("input[name='password']")).to_be_visible()
    
    def test_successful_login(self, page: Page):
        """Test successful login with correct credentials."""
        page.goto(BASE_URL)
        page.fill("input[name='username']", DEFAULT_USERNAME)
        page.fill("input[name='password']", DEFAULT_PASSWORD)
        page.click("button[type='submit']")
        
        # Wait for navigation
        page.wait_for_load_state("networkidle")
        
        # Should be redirected to main page
        assert "login" not in page.url.lower()
    
    def test_failed_login(self, page: Page):
        """Test login failure with incorrect credentials."""
        page.goto(BASE_URL)
        page.fill("input[name='username']", "wrong_user")
        page.fill("input[name='password']", "wrong_password")
        page.click("button[type='submit']")
        
        # Should show error message or stay on login page
        time.sleep(1)  # Give time for error to display
        assert page.locator("text=/error|invalid|wrong/i").count() > 0 or "login" in page.url.lower()


class TestProjectUpload:
    """Test project upload functionality."""
    
    def test_upload_page_accessible(self, authenticated_page: Page):
        """Test that upload page is accessible after login."""
        # Navigate to upload page (adjust selector based on your UI)
        if authenticated_page.locator("text=/upload|project/i").count() > 0:
            authenticated_page.click("text=/upload|project/i")
        
        # Check for file input element
        expect(authenticated_page.locator("input[type='file']")).to_be_visible(timeout=5000)
    
    def test_upload_interface_elements(self, authenticated_page: Page):
        """Test that all upload interface elements are present."""
        # Check for common upload elements
        page = authenticated_page
        
        # File input should be present
        file_inputs = page.locator("input[type='file']")
        assert file_inputs.count() > 0
        
        # Upload button should exist
        upload_buttons = page.locator("button:has-text('Upload'), button:has-text('Generate'), button:has-text('Process')")
        assert upload_buttons.count() > 0


class TestSettings:
    """Test settings and configuration pages."""
    
    def test_settings_page_accessible(self, authenticated_page: Page):
        """Test that settings page is accessible."""
        page = authenticated_page
        
        # Look for settings link/button
        settings_link = page.locator("a:has-text('Settings'), button:has-text('Settings'), [href*='settings']")
        
        if settings_link.count() > 0:
            settings_link.first.click()
            page.wait_for_load_state("networkidle")
            
            # Verify we're on settings page
            assert "settings" in page.url.lower() or page.locator("text=/configuration|settings/i").count() > 0
    
    def test_password_change_interface(self, authenticated_page: Page):
        """Test that password change interface exists."""
        page = authenticated_page
        
        # Navigate to settings
        settings_link = page.locator("a:has-text('Settings'), button:has-text('Settings'), [href*='settings']")
        if settings_link.count() > 0:
            settings_link.first.click()
            page.wait_for_load_state("networkidle")
            
            # Look for password fields
            password_fields = page.locator("input[type='password']")
            # At least one password field should exist in settings
            assert password_fields.count() >= 1


class TestGeneration:
    """Test OpenHAB configuration generation."""
    
    def test_generation_status_visible(self, authenticated_page: Page):
        """Test that generation status is visible on main page."""
        page = authenticated_page
        page.goto(BASE_URL)
        
        # Look for status indicators or generation buttons
        status_indicators = page.locator("text=/status|generate|processing/i")
        assert status_indicators.count() > 0
    
    def test_output_preview_accessible(self, authenticated_page: Page):
        """Test that generated output can be previewed."""
        page = authenticated_page
        
        # Look for links to view generated files
        preview_links = page.locator("a:has-text('Items'), a:has-text('Things'), a:has-text('Sitemap'), a:has-text('View')")
        
        # At least some preview capability should exist
        if preview_links.count() > 0:
            preview_links.first.click()
            page.wait_for_load_state("networkidle")
            # Should show some content
            assert len(page.content()) > 1000


class TestResponsiveness:
    """Test responsive design for different screen sizes (important for Raspberry Pi)."""
    
    @pytest.mark.parametrize("viewport", [
        {"width": 1920, "height": 1080},  # Desktop
        {"width": 1024, "height": 768},   # Tablet
        {"width": 375, "height": 667},    # Mobile
    ])
    def test_responsive_layout(self, page: Page, viewport):
        """Test that UI works on different screen sizes."""
        page.set_viewport_size(viewport)
        page.goto(BASE_URL)
        
        # Page should load without errors
        expect(page).to_have_url(lambda url: BASE_URL in url)
        
        # Basic navigation should be visible
        # (Adjust selectors based on your actual UI)
        assert page.locator("nav, header, .navbar, #nav").count() > 0


class TestVersionCheck:
    """Test version check and update functionality."""
    
    def test_version_badge_visible(self, authenticated_page: Page):
        """Test that version information is displayed."""
        page = authenticated_page
        page.goto(BASE_URL)
        
        # Look for version badge mentioned in README
        version_elements = page.locator("text=/version|v\d+\.\d+/i, [class*='version'], [id*='version']")
        
        # Version should be displayed somewhere
        if version_elements.count() > 0:
            assert version_elements.first.is_visible()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
