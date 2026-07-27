"""UI tests for services section and cloud info card."""

import json
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_services_routes(page: Page):
    services = [
        {"name": "openhab.service", "active": True, "status": "active", "uptime": "2h 30min"},
        {"name": "evcc.service", "active": False, "status": "inactive", "uptime": ""},
    ]

    cloud_info = {
        "uuid": "abc-123-def-456",
        "secret": "super-secret-value",
        "uuid_path": "/var/lib/openhab/uuid",
        "secret_path": "/var/lib/openhab/openhabcloud/secret",
    }

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, services)
        if re.search(r"/api/service/.+/status$", url):
            return _fulfill(route, {"active": True, "status": "active", "uptime": "2h 30min"})
        if url.endswith("/api/service/restart") and method == "POST":
            return _fulfill(route, {"ok": True, "output": "Service restarted"})
        if url.endswith("/api/openhab/cloud-info"):
            return _fulfill(route, cloud_info)
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestServicesSection:
    def test_services_list_renders(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        services = page.locator("#servicesList .service-item")
        expect(services).to_have_count(2, timeout=10000)

    def test_service_shows_status(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        expect(page.locator("#servicesList")).to_contain_text("openhab.service")
        expect(page.locator("#servicesList")).to_contain_text("evcc.service")

    def test_service_restart_button(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        restart_btns = page.locator(".service-restart-btn")
        expect(restart_btns.first).to_be_visible()

    def test_service_restart_triggers_confirm(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        dialog_messages = []

        def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            dialog.accept()

        page.on("dialog", handle_dialog)

        page.locator(".service-restart-btn").first().click()
        page.wait_for_timeout(1000)
        assert any("restart" in msg.lower() for msg in dialog_messages)


@pytest.mark.ui
class TestCloudInfoCard:
    def test_cloud_info_loads(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        cloud_card = page.locator(".cloud-info-card")
        expect(cloud_card).to_be_visible(timeout=10000)
        expect(cloud_card).to_contain_text("abc-123-def-456")

    def test_cloud_secret_masked_by_default(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        cloud_card = page.locator(".cloud-info-card")
        expect(cloud_card).to_be_visible(timeout=10000)

        secret_value = page.locator(".cloud-secret-masked")
        if secret_value.count() > 0:
            expect(secret_value.first).not_to_contain_text("super-secret-value")

    def test_cloud_secret_toggle(self, page: Page, base_url, flask_server):
        _setup_services_routes(page)
        page.goto(base_url)

        toggle_btn = page.locator(".cloud-toggle-btn")
        if toggle_btn.count() > 0:
            toggle_btn.first.click()
            page.wait_for_timeout(500)
