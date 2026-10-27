"""UI tests for services section and cloud info card."""

import json
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_services_routes(page: Page):
    cloud_info = {
        "uuid": "abc-123-def-456",
        "secret": "super-secret-value",
        "uuid_path": "/var/lib/openhab/uuid",
        "secret_path": "/var/lib/openhab/openhabcloud/secret",
    }
    restart_requests = []

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/service/updates/status"):
            return _fulfill(route, {"action": None, "state": "idle", "message": ""})
        if re.search(r"/api/service/(openhab|evcc)/version$", url):
            return _fulfill(
                route,
                {
                    "installed": "5.0.0-1",
                    "candidate": "5.0.0-1",
                    "supported": True,
                    "update_available": False,
                    "message": "APT candidate from local package lists.",
                },
            )
        if re.search(r"/api/service/(openhab|evcc)\.service/status$", url):
            service = re.search(r"/api/service/([^/]+)/status$", url).group(1)
            active = service == "openhab.service"
            return _fulfill(
                route,
                {
                    "active": active,
                    "status": "active" if active else "inactive",
                    "uptime_str": (
                        "ActiveEnterTimestamp=Mon 2026-10-26 10:00:00 UTC" if active else None
                    ),
                    "last_run_str": None,
                },
            )
        if url.endswith("/api/service/restart") and method == "POST":
            restart_requests.append(json.loads(request.post_data or "{}"))
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
    return restart_requests


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

        restart_btns = page.locator("#servicesList .restart-btn")
        expect(restart_btns.first).to_be_visible()

    def test_service_restart_posts_selected_service(self, page: Page, base_url, flask_server):
        restart_requests = _setup_services_routes(page)
        page.goto(base_url)

        restart_btn = page.locator("#servicesList .restart-btn").first
        with page.expect_response("**/api/service/restart") as response_info:
            restart_btn.click()

        assert response_info.value.status == 200
        assert json.loads(response_info.value.request.post_data or "{}") == {
            "service": "openhab.service"
        }
        expect(restart_btn).to_have_text("Restart")
        assert restart_requests == [{"service": "openhab.service"}]


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
        secret_value = page.locator("#cloud-secret-val")
        expect(toggle_btn).to_be_visible(timeout=10000)
        expect(secret_value).to_have_class(re.compile(r"cloud-secret-masked"))

        toggle_btn.click()

        expect(secret_value).to_have_text("super-secret-value")
        expect(secret_value).not_to_have_class(re.compile(r"cloud-secret-masked"))
