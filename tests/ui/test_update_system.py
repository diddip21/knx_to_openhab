"""UI tests for update system (version check, dialogs, log)."""

import json
import os
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_version_routes(
    page: Page,
    update_available=False,
    log_state=None,
    update_response=None,
    update_status=200,
):
    calls = {"update": 0, "log": 0}
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
            calls["update"] += 1
            if callable(update_response):
                response_data, response_status = update_response(calls["update"])
                return _fulfill(route, response_data, status=response_status)
            return _fulfill(
                route,
                update_response
                or {
                    "status": "updating",
                    "message": "Update request for v1.4.0 (request_id=" + "b" * 32 + ") started",
                },
                status=update_status,
            )
        if url.endswith("/api/version/log"):
            calls["log"] += 1
            update_log = (
                log_state["value"]
                if log_state is not None
                else (
                    "Update queued for v1.4.0 (request_id="
                    + "b" * 32
                    + ").\nStarting update...\nRelease archive verified"
                )
            )
            return _fulfill(route, {"log": update_log})
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
    return calls


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

    def test_update_dialog_language_switch_preserves_version_details(
        self, page: Page, base_url, flask_server
    ):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)
        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        expect(page.locator("#updateDialog h2 span")).to_have_text("Systemupdate verfügbar")
        page.get_by_role("combobox", name="Sprache / Language").select_option("en")
        expect(page.locator("#updateDialog h2 span")).to_have_text("System Update Available")
        expect(page.locator("#dialogCurrentCommit")).to_have_text("abc1234")
        expect(page.locator("#dialogLatestCommit")).to_have_text("def5678")
        expect(page.locator("#dialogLatestMessage")).to_have_text("Latest improvement")

        page.get_by_role("combobox", name="Sprache / Language").select_option("de")
        expect(page.locator("#updateDialog h2 span")).to_have_text("Systemupdate verfügbar")
        expect(page.locator("#dialogLatestAuthor")).to_have_text("developer")

    def test_update_dialog_install_button(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        install_btn = page.locator("#dialogUpdateBtn")
        expect(install_btn).to_be_visible()

    def test_update_button_starts_update_and_polls_log(self, page: Page, base_url, flask_server):
        calls = _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()

        expect(page.locator("#updateLogModal[open]")).to_be_visible()
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Release archive verified", timeout=10000
        )
        assert calls["update"] == 1
        assert calls["log"] >= 1

    def test_success_dialog_waits_for_health_validation(self, page: Page, base_url, flask_server):
        request_id = "b" * 32
        log_state = {
            "value": (
                f"Update queued for v1.4.0 (request_id={request_id}).\n"
                "Restarting knxohui.service on release v1.4.0..."
            )
        }
        _setup_version_routes(page, update_available=True, log_state=log_state)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()

        expect(page.locator("#updateLogContent")).to_contain_text(
            "Restarting knxohui.service", timeout=10000
        )
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

        log_state["value"] += "\nUpdate completed successfully!"
        log_state["value"] += f" (request_id={request_id})"
        expect(page.locator("#updateSuccessDialog[open]")).to_be_visible(timeout=5000)
        if os.environ.get("CAPTURE_PR70_UPDATE_SCREENSHOT") == "1":
            page.screenshot(path="docs/screenshots/pr70-update-success-dialog.png", full_page=True)

    def test_stale_success_log_is_ignored_until_current_request_and_rollback(
        self, page: Page, base_url, flask_server
    ):
        old_request_id = "a" * 32
        current_request_id = "b" * 32
        log_state = {
            "value": (
                f"Update queued for v1.4.0 (request_id={old_request_id}).\n"
                "Update completed successfully!"
            )
        }
        calls = _setup_version_routes(page, update_available=True, log_state=log_state)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()

        expect(page.locator("#updateLogContent")).to_contain_text("started", timeout=5000)
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
        page.wait_for_timeout(1200)
        assert calls["log"] >= 1
        expect(page.locator("#updateLogContent")).not_to_contain_text(
            "Update completed successfully"
        )
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

        log_state["value"] = (
            f"Update queued for v1.4.0 (request_id={current_request_id}).\n"
            "Restarting knxohui.service on release v1.4.0..."
        )
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Restarting knxohui.service", timeout=5000
        )
        log_state["value"] += (
            "\nThe updated service did not pass its health check.\n"
            "Previous release restored and health check passed."
        )
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Previous release restored", timeout=5000
        )
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

    def test_update_startup_error_is_not_overwritten_by_log_polling(
        self, page: Page, base_url, flask_server
    ):
        calls = _setup_version_routes(
            page,
            update_available=True,
            log_state={"value": "Update completed successfully! from an older request"},
            update_response={"error": "The updater is already running."},
            update_status=409,
        )
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()

        expect(page.locator("#updateLogContent")).to_contain_text(
            "updater is already running", timeout=10000
        )
        page.wait_for_timeout(1200)
        assert calls["log"] == 0
        expect(page.locator("#updateLogContent")).to_contain_text("updater is already running")
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

    def test_success_from_a_different_request_is_ignored(self, page: Page, base_url, flask_server):
        current_request_id = "b" * 32
        other_request_id = "a" * 32
        log_state = {
            "value": (
                f"Update queued for v1.4.0 (request_id={current_request_id}).\n"
                "Restarting knxohui.service on release v1.4.0..."
            )
        }
        _setup_version_routes(page, update_available=True, log_state=log_state)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Restarting knxohui.service", timeout=10000
        )

        log_state["value"] = (
            f"Update queued for v1.4.0 (request_id={other_request_id}).\n"
            "Update completed successfully!"
        )
        page.wait_for_timeout(1300)

        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)
        expect(page.locator("#updateLogContent")).not_to_contain_text(
            "Update completed successfully"
        )

    def test_success_without_current_request_marker_is_ignored(
        self, page: Page, base_url, flask_server
    ):
        request_id = "b" * 32
        log_state = {
            "value": (
                f"Update queued for v1.4.0 (request_id={request_id}).\n"
                "Restarting knxohui.service on release v1.4.0..."
            )
        }
        _setup_version_routes(page, update_available=True, log_state=log_state)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Restarting knxohui.service", timeout=10000
        )
        log_state["value"] += "\nUpdate completed successfully!"
        page.wait_for_timeout(1300)

        expect(page.locator("#updateLogContent")).to_contain_text("Update completed successfully")
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

    def test_old_poll_cannot_overwrite_new_attempt_startup_error(
        self, page: Page, base_url, flask_server
    ):
        request_id = "b" * 32
        log_state = {
            "value": (
                f"Update queued for v1.4.0 (request_id={request_id}).\n"
                "Restarting knxohui.service on release v1.4.0..."
            )
        }

        def update_response(call_number):
            if call_number == 1:
                return (
                    {
                        "status": "updating",
                        "message": f"Update request for v1.4.0 (request_id={request_id}) started",
                    },
                    200,
                )
            log_state["value"] += f"\nUpdate completed successfully! (request_id={request_id})"
            return ({"error": "The updater is already running."}, 409)

        calls = _setup_version_routes(
            page,
            update_available=True,
            log_state=log_state,
            update_response=update_response,
        )
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()
        expect(page.locator("#updateLogContent")).to_contain_text(
            "Restarting knxohui.service", timeout=10000
        )
        page.locator("#updateLogModal .close-btn").click()
        expect(page.locator("#updateLogModal[open]")).to_have_count(0)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)
        page.locator("#dialogUpdateBtn").click()
        expect(page.locator("#updateLogContent")).to_contain_text(
            "updater is already running", timeout=10000
        )
        page.wait_for_timeout(1300)

        assert calls["update"] == 2
        expect(page.locator("#updateLogContent")).to_contain_text("updater is already running")
        expect(page.locator("#updateSuccessDialog[open]")).to_have_count(0)

    def test_update_dialog_cancel(self, page: Page, base_url, flask_server):
        _setup_version_routes(page, update_available=True)
        page.goto(base_url)

        page.locator("#versionBadge").click()
        expect(page.locator("#updateDialog[open]")).to_be_visible(timeout=10000)

        page.locator("#updateDialog .close-btn").click()
        expect(page.locator("#updateDialog[open]")).to_have_count(0, timeout=5000)
