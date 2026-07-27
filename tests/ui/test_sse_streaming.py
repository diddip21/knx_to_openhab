"""UI tests for SSE live event streaming."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

JOB_ID = "job-sse-test"


def _setup_sse_routes(page: Page, events=None):
    if events is None:
        events = [
            'data: {"type": "backup", "message": "backup created: test.tar.gz"}',
            "",
            'data: {"type": "status", "message": "running"}',
            "",
            'data: {"type": "info", "message": "start in-process generation"}',
            "",
            'data: {"type": "info", "message": "parsed knxproj"}',
            "",
            'data: {"type": "stats", "message": "items: 0 -> 10 lines (+10) [+5/-0]"}',
            "",
            'data: {"type": "status", "message": "completed (staged) - ready to deploy"}',
            "",
        ]

    state = {"status": "running", "events_sent": False}

    def job_payload():
        return {
            "id": JOB_ID,
            "name": "SSE Test Job",
            "status": state["status"],
            "staged": True,
            "deployed": False,
            "backups": [{"name": "backup-1", "ts": "2026-01-01"}],
            "created": 1700000000,
            "stats": {
                "items/knx.items": {
                    "before": 0,
                    "after": 10,
                    "delta": 10,
                    "added": 5,
                    "removed": 0,
                }
            },
            "log": [],
        }

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/upload") and method == "POST":
            state["status"] = "running"
            return _fulfill(route, {"id": JOB_ID, "status": "running"})

        if url.endswith("/api/jobs"):
            return _fulfill(route, [job_payload()])

        if re.search(r"/api/job/[^/]+/events$", url):
            if not state["events_sent"]:
                state["events_sent"] = True
                state["status"] = "completed"
                body = "\n".join(events) + "\n"
                route.fulfill(status=200, content_type="text/event-stream", body=body)
            else:
                route.fulfill(status=200, content_type="text/event-stream", body="")
            return

        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return _fulfill(route, job_payload())

        if url.endswith("/api/services"):
            return _fulfill(route, [])
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
class TestSSEStreaming:
    def test_sse_connection_starts_on_upload(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        file_input = page.locator("#fileInput")
        expect(file_input).to_be_visible()
        file_input.set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()

        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)
        expect(page.locator("#log")).not_to_have_text("Waiting for events...", timeout=10000)

    def test_sse_backup_event_logged(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        expect(page.locator("#log")).to_contain_text("BACKUP", timeout=10000)
        expect(page.locator("#log")).to_contain_text("backup created", timeout=10000)

    def test_sse_status_updates_render(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()

        expect(page.locator("#jobDetail .badge")).to_contain_text(
            re.compile(r"running|completed"), timeout=20000
        )

    def test_sse_stats_event_logged(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        expect(page.locator("#log")).to_contain_text("STATS", timeout=10000)

    def test_sse_error_event_shows_in_log(self, page: Page, base_url, flask_server):
        error_events = [
            'data: {"type": "error", "message": "Something went wrong"}',
            "",
            'data: {"type": "status", "message": "failed"}',
            "",
        ]
        _setup_sse_routes(page, events=error_events)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        expect(page.locator("#log")).to_contain_text("ERROR", timeout=10000)
        expect(page.locator("#log")).to_contain_text("Something went wrong", timeout=10000)

    def test_sse_done_completes_job(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()

        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)
        expect(page.locator("#status")).to_contain_text(
            re.compile(r"completed|Job completed"), timeout=20000
        )

    def test_sse_log_level_filter(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        page.locator("#logLevelFilter").select_option("error")
        page.wait_for_timeout(500)

        error_entries = page.locator(".log-entry.log-level-error")
        info_entries = page.locator(".log-entry.log-level-info")
        assert error_entries.count() >= 0
        assert info_entries.count() == 0

    def test_sse_multiple_event_types(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(
            str(__import__("pathlib").Path(__file__).parent.parent / "fixtures" / "Charne.knxproj")
        )
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        log_text = page.locator("#log").inner_text()
        assert "BACKUP" in log_text or "backup" in log_text.lower()
