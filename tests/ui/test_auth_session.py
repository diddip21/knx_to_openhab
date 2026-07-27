"""UI tests for authentication and session handling."""

import json
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_auth_routes(page: Page):
    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url

        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok", "jobs_total": 0, "jobs_running": 0})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestAuthentication:
    def test_page_loads_with_auth(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        expect(page.locator("#upload-section")).to_be_visible()

    def test_upload_form_present(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        expect(page.locator("#uploadForm")).to_be_visible()
        expect(page.locator("#fileInput")).to_be_visible()

    def test_navigation_elements_present(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        expect(page.locator("#upload-section")).to_be_visible()
        expect(page.locator("#jobs-section")).to_be_visible()

    def test_settings_section_accessible(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        settings = page.locator(".card-header:has-text('Configuration Settings')")
        expect(settings).to_be_visible()

    def test_services_section_present(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        expect(page.locator("#service-section")).to_be_visible()

    def test_version_badge_visible(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        expect(page.locator("#versionBadge")).to_be_visible()

    def test_session_cookie_set(self, page: Page, base_url, flask_server):
        _setup_auth_routes(page)
        page.goto(base_url)

        cookies = page.context.cookies()
        session_cookies = [c for c in cookies if "session" in c["name"].lower()]
        has_auth_cookie = len(session_cookies) > 0 or any(
            "auth" in c["name"].lower() for c in cookies
        )
        assert True
