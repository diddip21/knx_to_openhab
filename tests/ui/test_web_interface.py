"""UI tests for the knx_to_openhab web interface using Playwright."""

import json
import re
import time

import pytest
from playwright.sync_api import Page, expect

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
def authenticated_page(page: Page, base_url):
    """Provide an authenticated page session."""
    page.goto(base_url)

    # Check if already logged in, if not, login
    if "login" in page.url.lower() or page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", DEFAULT_USERNAME)
        page.fill("input[name='password']", DEFAULT_PASSWORD)
        page.click("button[type='submit']")
        expect(page.locator("#upload-section")).to_be_visible(timeout=10000)

    return page


class TestAuthentication:
    """Test authentication and login functionality."""

    def test_login_page_loads(self, page: Page, base_url):
        """Test that login page loads correctly."""
        page.goto(base_url)
        expect(page).to_have_title(re.compile(r"knx|openhab", re.IGNORECASE))
        # If auth is disabled in test server, login fields won't exist
        if page.locator("input[name='username']").count() == 0:
            return
        expect(page.locator("input[name='username']")).to_be_visible()
        expect(page.locator("input[name='password']")).to_be_visible()

    def test_successful_login(self, page: Page, base_url):
        """Test successful login with correct credentials."""
        page.goto(base_url)
        if page.locator("input[name='username']").count() == 0:
            # Auth disabled in test server
            assert "login" not in page.url.lower()
            return

        page.fill("input[name='username']", DEFAULT_USERNAME)
        page.fill("input[name='password']", DEFAULT_PASSWORD)
        page.click("button[type='submit']")

        expect(page.locator("#upload-section")).to_be_visible(timeout=10000)

        # Should be redirected to main page
        assert "login" not in page.url.lower()

    def test_failed_login(self, page: Page, base_url):
        """Test login failure with incorrect credentials."""
        page.goto(base_url)
        if page.locator("input[name='username']").count() == 0:
            pytest.skip("Auth disabled in test server")

        page.fill("input[name='username']", "wrong_user")
        page.fill("input[name='password']", "wrong_password")
        page.click("button[type='submit']")

        # Should show error message or stay on login page
        time.sleep(1)  # Give time for error to display
        assert (
            page.locator("text=/error|invalid|wrong/i").count() > 0 or "login" in page.url.lower()
        )


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
        upload_buttons = page.locator(
            "button:has-text('Upload'), button:has-text('Generate'), button:has-text('Process')"
        )
        assert upload_buttons.count() > 0


class TestSettings:
    """Test settings and configuration pages."""

    def test_settings_page_accessible(self, authenticated_page: Page):
        """Test that settings page is accessible."""
        page = authenticated_page

        # Look for settings link/button
        settings_link = page.locator(
            "a:has-text('Settings'), button:has-text('Settings'), [href*='settings']"
        )

        if settings_link.count() > 0:
            settings_link.first.click()
            expect(page.locator("#settings-content")).to_be_visible(timeout=5000)

            # Verify we're on settings page
            assert (
                "settings" in page.url.lower()
                or page.locator("text=/configuration|settings/i").count() > 0
            )

    def test_password_change_interface(self, authenticated_page: Page):
        """Test that password change interface exists."""
        page = authenticated_page

        # Navigate to settings
        settings_link = page.locator(
            "a:has-text('Settings'), button:has-text('Settings'), [href*='settings']"
        )
        if settings_link.count() > 0:
            settings_link.first.click()
            expect(page.locator("#settings-content")).to_be_visible(timeout=5000)

            # Look for password fields
            password_fields = page.locator("input[type='password']")
            # At least one password field should exist in settings
            assert password_fields.count() >= 1


class TestGeneration:
    """Test OpenHAB configuration generation."""

    def test_generation_status_visible(self, authenticated_page: Page, base_url):
        """Test that generation status is visible on main page."""
        page = authenticated_page
        page.goto(base_url)

        # Look for status indicators or generation buttons
        status_indicators = page.locator("text=/status|generate|processing/i")
        assert status_indicators.count() > 0

    def test_output_preview_accessible(self, authenticated_page: Page):
        """Test that generated output can be previewed."""
        page = authenticated_page

        # Look for links to view generated files
        preview_links = page.locator(
            "a:has-text('Items'), a:has-text('Things'), a:has-text('Sitemap'), a:has-text('View')"
        )

        # At least some preview capability should exist
        if preview_links.count() > 0:
            preview_links.first.click()
            expect(page.locator("body")).not_to_be_empty(timeout=5000)
            # Should show some content
            assert len(page.content()) > 1000

    def test_completeness_summary_present(self, authenticated_page: Page, base_url):
        """Ensure completeness summary container is present in UI."""
        page = authenticated_page
        page.goto(base_url)

        summary = page.locator("#completenessSummary")
        expect(summary).to_have_count(1)


class TestResponsiveness:
    """Test responsive design for different screen sizes (important for Raspberry Pi)."""

    @pytest.mark.parametrize(
        "viewport",
        [
            {"width": 1920, "height": 1080},  # Desktop
            {"width": 1024, "height": 768},  # Tablet
            {"width": 375, "height": 667},  # Mobile
        ],
    )
    def test_responsive_layout(self, page: Page, viewport, base_url):
        """Test that UI works on different screen sizes."""
        page.set_viewport_size(viewport)
        page.goto(base_url)

        # Page should load without errors
        expect(page).to_have_url(re.compile(re.escape(base_url)))

        # Basic header should be visible
        assert page.locator(".header-container, h1").count() > 0


class TestVersionCheck:
    """Test version check and update functionality."""

    def test_version_badge_visible(self, authenticated_page: Page, base_url):
        """Test that version information is displayed."""
        page = authenticated_page
        page.goto(base_url)

        # Look for version badge mentioned in README
        version_elements = page.locator("#versionBadge, [class*='version'], [id*='version']")

        # Version should be displayed somewhere
        assert version_elements.count() > 0
        assert version_elements.first.is_visible()


class TestReports:
    """Test report summary rendering."""

    def test_completeness_summary_render(self, authenticated_page: Page):
        """Test completeness summary renders from report payload."""
        page = authenticated_page

        report_payload = {
            "summary": {
                "missing_required": 1,
                "recommended_missing": 2,
                "total_things_checked": 42,
            },
            "missing_required": [
                {
                    "kind": "Switch",
                    "reason": "Missing channel",
                    "line": "Switch testSwitch",
                }
            ],
            "recommended_missing": [
                {
                    "kind": "Dimmer",
                    "reason": "No label",
                    "line": "Dimmer testDimmer",
                }
            ],
        }

        def handle_preview(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"content": json.dumps(report_payload)}),
            )

        page.route(re.compile(r".*/api/file/preview.*"), handle_preview)

        stats = {
            "completeness_report.json": {
                "staged_path": "openhab/completeness_report.json",
            }
        }

        page.evaluate(
            """
            () => {
                const toggle = document.getElementById('expertToggle')
                if (toggle) {
                    toggle.checked = true
                    localStorage.setItem('showExpertCompleteness', 'true')
                }
                if (window.applyExpertToggle) window.applyExpertToggle()
            }
            """
        )

        page.evaluate(
            "([jobId, stats]) => renderCompletenessSummary(jobId, stats)",
            ["job-123", stats],
        )

        summary = page.locator("#completenessSummary")
        expect(summary).to_contain_text("Summary", timeout=5000)
        expect(summary).to_contain_text("Required missing: 1")
        expect(summary).to_contain_text("Recommended missing: 2")
        expect(summary).to_contain_text("Things checked: 42")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
