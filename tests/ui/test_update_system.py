"""UI tests for update system (version check, dialogs, log)."""

import json
import os
import re
from pathlib import Path

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
        expect(page.locator("#dialogUpdateBtn")).to_be_visible()

    def test_update_dialog_cancel(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)
        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#updateDialog .close-btn").click()
        expect(page.locator("#updateDialog[open]")).to_have_count(0, timeout=5000)


REQUEST_ID = "10000000-0000-4000-8000-000000000001"
OLD_REQUEST_ID = "10000000-0000-4000-8000-000000000002"


def _start_release_update(page, base_url, states, *, submission=None, submission_error=False):
    """Use actual app.js/dialogs against a real local Flask app, fake only APIs."""
    _setup_version_routes(page, update_available=True)
    if os.environ.get("KNXOH_UPDATE_SCREENSHOTS") == "1":
        # Capture the real app's honest current-version fields, not fixture hashes.
        page.route("**/api/version", lambda route: route.continue_())
    polls = []

    def update(route):
        if submission_error:
            route.abort()
        else:
            route.fulfill(
                status=200 if submission is None else 500,
                json=submission
                or {
                    "status": "updating",
                    "message": "Request claimed",
                    "request_id": REQUEST_ID,
                },
            )

    def log(route):
        polls.append(1)
        value = states[min(len(polls) - 1, len(states) - 1)]
        if value is None:
            route.abort()
        else:
            route.fulfill(json=value)

    page.route("**/api/version/update", update)
    page.route("**/api/version/log", log)
    page.goto(base_url)
    page.locator("#versionBadge").click()
    expect(page.locator("#updateDialog[open]")).to_be_visible()
    page.locator("#dialogUpdateBtn").click()
    return polls


def _phase(phase, message, outcome="running", request_id=REQUEST_ID):
    return {
        "log": f"{phase}: {message}\n",
        "update": {
            "request_id": request_id,
            "phase": phase,
            "message": message,
            "outcome": outcome,
        },
    }


@pytest.mark.ui
def test_committed_only_after_matching_request_and_restart_disconnect(page, base_url, flask_server):
    page.clock.install()
    states = [
        _phase("committed", "Old release completed", "updated", OLD_REQUEST_ID),
        _phase("activated", "Restart initiated; readiness not yet confirmed"),
        _phase("checking", "Waiting for readiness"),
        None,
        _phase("committed", "Release update completed", "updated"),
    ]
    polls = _start_release_update(page, base_url, states)
    expect(page.locator("#updateLogContent")).to_contain_text("Waiting for readiness", timeout=6000)
    expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
    _capture_update_state(page, "update-release-checking.png")
    expect(page.locator("#updateSuccessDialog[open]")).to_be_visible(timeout=7000)
    _capture_update_state(page, "update-release-committed.png")
    count = len(polls)
    page.wait_for_timeout(1200)
    assert len(polls) == count  # terminal status actually stops the consumer
    with page.expect_navigation(wait_until="load"):
        page.clock.run_for(16000)


def _capture_update_state(page, name):
    if os.environ.get("KNXOH_UPDATE_SCREENSHOTS") == "1":
        directory = Path(__file__).resolve().parents[2] / "docs/screenshots"
        directory.mkdir(exist_ok=True)
        page.screenshot(path=str(directory / name), full_page=True, animations="disabled")


@pytest.mark.ui
@pytest.mark.parametrize(
    "message,outcome",
    [
        ("No newer compatible release", "no-update"),
        ("Update failed; previous release preserved", "failed"),
    ],
)
def test_rollback_and_no_update_stop_without_success(
    page, base_url, flask_server, message, outcome
):
    polls = _start_release_update(page, base_url, [_phase("rolled-back", message, outcome)])
    expect(page.locator("#updateLogContent")).to_contain_text(message)
    expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
    count = len(polls)
    page.wait_for_timeout(1600)
    assert len(polls) == count


@pytest.mark.ui
@pytest.mark.parametrize("disconnected", [False, True])
def test_failed_submission_never_consumes_old_terminal(page, base_url, flask_server, disconnected):
    polls = _start_release_update(
        page,
        base_url,
        [_phase("committed", "Old release completed", "updated")],
        submission={"error": "No matching updater acknowledgement"},
        submission_error=disconnected,
    )
    expect(page.locator("#updateLogContent")).to_contain_text(
        "failed" if disconnected else "No matching"
    )
    page.wait_for_timeout(1600)
    assert polls == []
    expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
