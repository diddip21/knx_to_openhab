"""The Services view resumes polling after a page reload."""

import json
import re

from playwright.sync_api import Page, expect


def test_running_package_operation_finishes_after_page_load(page: Page, base_url):
    state = {"status_calls": 0}

    def fulfill(route, payload):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def service_route(route, request):
        url = request.url
        if url.endswith("/api/service/updates/status"):
            state["status_calls"] += 1
            running = state["status_calls"] == 1
            return fulfill(
                route,
                {
                    "action": "openhab",
                    "state": "running" if running else "completed",
                    "message": "Installing package" if running else "Update finished.",
                },
            )
        if re.search(r"/api/service/[^/]+\.service/status$", url):
            return fulfill(route, {"active": True, "status": "active"})
        if re.search(r"/api/service/(openhab|evcc)/version$", url):
            return fulfill(
                route,
                {
                    "installed": "5.0.0-1",
                    "candidate": "5.1.0-1",
                    "supported": True,
                    "update_available": True,
                    "message": "APT candidate from local package lists.",
                },
            )
        return route.continue_()

    page.route("**/api/service/**", service_route)
    page.goto(base_url)

    expect(page.locator("#packageOperationStatus")).to_contain_text(
        "Update finished.", timeout=10000
    )
    expect(page.locator("#refreshPackagesBtn")).to_be_enabled()
    assert state["status_calls"] >= 2
