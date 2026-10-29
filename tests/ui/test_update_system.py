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


@pytest.mark.ui
@pytest.mark.parametrize(
    "delay,b_outcome,a_outcome",
    [
        ("headers", "polling", "success"),
        ("body", "polling", "success"),
        ("headers", "failed", "success"),
        ("body", "failed", "success"),
        ("headers", "polling", "rejected"),
        ("headers", "polling", "disconnected"),
        ("headers", "committed", "success"),
    ],
)
def test_superseded_submission_cannot_adopt_or_mutate_new_attempt(
    page, base_url, flask_server, delay, b_outcome, a_outcome
):
    """Delay real fetch/body promises; use the actual close/reopen UI for B."""
    page.clock.install()
    page.add_init_script("""
        window.__holdABody = false;
        window.__aSettled = false;
        window.__aBodyReady = false;
        window.__postCount = 0;
        window.__aBodyGate = new Promise(resolve => { window.__releaseABody = resolve });
        const realFetch = window.fetch;
        window.fetch = async (resource, options) => {
          const index = resource === '/api/version/update' ? ++window.__postCount : 0;
          try {
            const response = await realFetch(resource, options);
            if (index === 1) {
              // A superseded attempt may now return immediately after fetch,
              // without ever reading its body. Observe both legitimate paths.
              if (!window.__holdABody) window.__aSettled = true;
              const read = response.json.bind(response);
              response.json = async () => {
                try {
                  const data = await read();
                  window.__aBodyReady = true;
                  if (window.__holdABody) await window.__aBodyGate;
                  return data;
                } finally { window.__aSettled = true }
              };
            }
            return response;
          } catch (error) {
            if (index === 1) window.__aSettled = true;
            throw error;
          }
        };
    """)
    _setup_version_routes(page, update_available=True)
    submissions = []
    polls = []
    projection = [_phase("checking", "B readiness", request_id=REQUEST_ID)]

    def defer_submission(route):
        submissions.append(route)

    def log(route):
        polls.append(1)
        route.fulfill(json=projection[0])

    page.route("**/api/version/update", defer_submission)
    page.route("**/api/version/log", log)
    page.goto(base_url)
    page.evaluate("hold => { window.__holdABody = hold }", delay == "body")
    page.locator("#versionBadge").click()
    expect(page.locator("#updateDialog[open]")).to_be_visible()
    page.locator("#dialogUpdateBtn").click()
    page.wait_for_function("window.__postCount === 1")
    assert len(submissions) == 1
    a_success = {"status": "updating", "request_id": OLD_REQUEST_ID, "message": "A claimed"}
    if delay == "body":
        submissions[0].fulfill(json=a_success)
        page.wait_for_function("window.__aBodyReady")

    # This is the real user path, not a second direct performUpdate() call.
    page.locator("#updateLogModal button", has_text="Close").click()
    page.locator("#versionBadge").click()
    expect(page.locator("#updateDialog[open]")).to_be_visible()
    page.locator("#dialogUpdateBtn").click()
    page.wait_for_function("window.__postCount === 2")
    assert len(submissions) == 2
    if b_outcome == "failed":
        submissions[1].fulfill(status=409, json={"error": "B busy; retry later"})
        expect(page.locator("#updateLogContent")).to_contain_text("B busy; retry later")
    else:
        if b_outcome == "committed":
            projection[0] = _phase("committed", "B completed", "updated", REQUEST_ID)
        submissions[1].fulfill(json={"status": "updating", "request_id": REQUEST_ID})
        if b_outcome == "committed":
            expect(page.locator("#updateSuccessDialog[open]")).to_be_visible()
        else:
            expect(page.locator("#updateLogContent")).to_contain_text("B readiness")

    before = page.evaluate("""() => ({
        request: activeUpdateRequestId, poller: updatePollInterval,
        reload: updateReloadInterval, message: document.getElementById('updateLogContent').textContent,
        countdown: document.getElementById('reloadCountdown').textContent
    })""")
    navigations = []
    page.on(
        "framenavigated",
        lambda frame: navigations.append(frame.url) if frame == page.main_frame else None,
    )
    # Old A completion is available, so accidentally adopting A would reload it.
    projection[0] = _phase("committed", "A completed", "updated", OLD_REQUEST_ID)
    if delay == "body":
        page.evaluate("window.__releaseABody()")
    elif a_outcome == "disconnected":
        submissions[0].abort()
    elif a_outcome == "rejected":
        submissions[0].fulfill(status=500, json={"error": "A rejected"})
    else:
        submissions[0].fulfill(json=a_success)
    page.wait_for_function("window.__aSettled")
    after = page.evaluate("""() => ({
        request: activeUpdateRequestId, poller: updatePollInterval,
        reload: updateReloadInterval, message: document.getElementById('updateLogContent').textContent,
        countdown: document.getElementById('reloadCountdown').textContent
    })""")
    # A cannot adopt identity/timers or overwrite B text. A running B countdown
    # may naturally tick down, but must never be replaced or reset by A.
    if b_outcome == "committed":
        assert 0 < int(after["countdown"]) <= int(before["countdown"])
        after["countdown"] = before["countdown"]
    assert after == before
    if b_outcome == "committed":
        with page.expect_navigation(wait_until="load"):
            page.clock.run_for(16000)  # B's existing countdown must still finish.
    else:
        page.clock.run_for(18000)
        assert navigations == []  # Neither old A nor uncommitted B may reload.
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
        assert page.locator("#updateLogContent").text_content() == before["message"]
        assert page.evaluate("activeUpdateRequestId") == before["request"]
        assert page.evaluate("updatePollInterval") == before["poller"]
        assert page.evaluate("updateReloadInterval") == before["reload"]
        if b_outcome == "failed":
            assert polls == []
        else:
            projection[0] = _phase("committed", "B completed", "updated", REQUEST_ID)
            expect(page.locator("#updateSuccessDialog[open]")).to_be_visible()
            with page.expect_navigation(wait_until="load"):
                page.clock.run_for(16000)
