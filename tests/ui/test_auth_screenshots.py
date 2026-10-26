from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
def test_login_and_authenticated_dashboard_screenshots(page: Page, auth_preview_server):
    screenshot_dir = Path("test-results/screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    page.goto(f"{auth_preview_server}/login")
    expect(page).to_have_title("Sign in · KNX to OpenHAB")
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    page.screenshot(path=str(screenshot_dir / "issue-22-login.png"), full_page=True)

    page.get_by_label("Username").fill("operator")
    page.get_by_label("Password").fill("test-only-preview-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()
    expect(page).to_have_title("KNX → OpenHAB Generator")
    page.screenshot(path=str(screenshot_dir / "issue-22-dashboard.png"), full_page=True)


@pytest.mark.ui
def test_expired_api_session_redirects_to_sign_in(
    page: Page, auth_preview_server, expire_auth_preview_session
):
    page.goto(f"{auth_preview_server}/login")
    page.get_by_label("Username").fill("operator")
    page.get_by_label("Password").fill("test-only-preview-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()

    expire_auth_preview_session()

    expect(page).to_have_url(f"{auth_preview_server}/login", timeout=15000)
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    screenshot_dir = Path("test-results/screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_dir / "issue-22-session-expired.png"), full_page=True)
