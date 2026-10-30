"""The Services view resumes polling after a page reload."""

import json
import re

from playwright.sync_api import Page, expect


def test_running_package_operation_finishes_after_page_load(page: Page, base_url, flask_server):
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
    expect(page.locator("#servicesList .service-item")).to_have_count(2, timeout=10000)
    assert state["status_calls"] >= 2


def test_polling_resumes_when_another_operation_starts_during_completion_refresh(
    page: Page, base_url, flask_server
):
    state = {"status_calls": 0}
    task_states = [
        ("running", "First operation running."),
        ("completed", "First operation finished."),
        ("running", "Second operation running in another tab."),
        ("completed", "Second operation finished."),
        ("completed", "Second operation finished."),
    ]

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
            index = min(state["status_calls"] - 1, len(task_states) - 1)
            task_state, message = task_states[index]
            return fulfill(
                route,
                {"action": "openhab", "state": task_state, "message": message},
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
        "Second operation finished.", timeout=15000
    )
    expect(page.locator("#refreshPackagesBtn")).to_be_enabled()
    assert state["status_calls"] >= 4


def test_polling_catches_operation_started_during_full_completion_refresh(
    page: Page, base_url, flask_server
):
    state = {"status_calls": 0, "replacement_started": False}
    task_states = [
        ("running", "First operation running."),
        ("completed", "First operation finished."),
        ("completed", "First operation finished."),
        ("running", "Second operation running in another tab."),
        ("running", "Second operation running in another tab."),
        ("running", "Second operation running in another tab."),
        ("completed", "Second operation is finishing."),
        ("completed", "Completion refresh settled."),
        ("completed", "Second operation finished."),
    ]

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
            index = min(state["status_calls"] - 1, len(task_states) - 1)
            task_state, message = task_states[index]
            return fulfill(
                route,
                {"action": "openhab", "state": task_state, "message": message},
            )
        if re.search(r"/api/service/[^/]+\.service/status$", url):
            return fulfill(route, {"active": True, "status": "active"})
        if re.search(r"/api/service/(openhab|evcc)/version$", url):
            if state["status_calls"] >= 3:
                state["replacement_started"] = True
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
        "Second operation finished.", timeout=20000
    )
    expect(page.locator("#refreshPackagesBtn")).to_be_enabled()
    assert state["replacement_started"]
    assert state["status_calls"] >= 9
