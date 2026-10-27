"""UI tests for update system (version check, dialogs, log)."""

import json
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_version_routes(page: Page, update_available=False):
    current_version = {
        "commit_short": "abc1234",
        "current_commit": "abc1234",
        "current_message": "Current release",
        "current_date": "2026-01-15",
    }
    latest_version = {
        "commit_short": "def5678",
        "latest_commit": "def5678",
        "latest_message": "Latest improvement",
        "latest_author": "developer",
        "latest_date": "2026-07-20",
        "commit_message": "Latest improvement",
        "commit_author": "developer",
        "commit_date": "2026-07-20",
    }

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/version"):
            return _fulfill(route, current_version)
        if url.endswith("/api/version/check"):
            return _fulfill(
                route,
                {
                    "update_available": update_available,
                    "current_commit": current_version["commit_short"],
                    "current_message": current_version["current_message"],
                    "current_date": current_version["current_date"],
                    "latest_commit": latest_version["commit_short"],
                    "latest_message": latest_version["commit_message"],
                    "latest_author": latest_version["commit_author"],
                    "latest_date": latest_version["commit_date"],
                },
            )
        if url.endswith("/api/version/update") and method == "POST":
            return _fulfill(route, {"status": "updating", "message": "Update started"})
        if url.endswith("/api/version/log"):
            return _fulfill(route, {"log": ["Starting update...", "Cloning repo...", "Done!"]})
        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestUpdateSystem:
    def test_version_badge_shows_version(self, page: Page, base_url, flask_server):
        _setup_version_routes(page)
        page.goto(base_url)

        badge = page.locator("#versionBadge")
        expect(badge).to_be_visible()
        expect(badge).to_contain_text("abc1234")

    def test_check_updates_no_update(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=False)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        page.wait_for_timeout(2000)

        expect(page.locator("#updateDialog[open]")).to_have_count(0, timeout=5000)

    def test_check_updates_available(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

    def test_update_dialog_shows_info(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        expect(page.locator("#dialogLatestCommit")).to_contain_text("def5678")
        expect(page.locator("#dialogLatestMessage")).to_contain_text("Latest improvement")

    def test_update_dialog_install_button(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        install_btn = page.locator("#dialogUpdateBtn")
        expect(install_btn).to_be_visible()

    def test_update_dialog_cancel(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        page.locator("#updateDialog .close-btn").click()
        expect(page.locator("#updateDialog[open]")).to_have_count(0, timeout=5000)
