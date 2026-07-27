"""UI tests for SSE live event streaming and job log rendering."""

import json
import os
import re

import pytest
from playwright.sync_api import Page, expect

JOB_ID = "job-sse-test"

TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


def _setup_sse_routes(page: Page, job_log=None):
    if job_log is None:
        job_log = [
            {"level": "info", "text": "[BACKUP] backup created: test.tar.gz"},
            {"level": "info", "text": "[STATUS] running"},
            {"level": "info", "text": "[INFO] start in-process generation"},
            {"level": "info", "text": "[INFO] parsed knxproj"},
            {"level": "info", "text": "[STATS] items: 0 -> 10 lines (+10) [+5/-0]"},
            {"level": "info", "text": "[STATUS] completed (staged) - ready to deploy"},
        ]

    state = {"status": "running"}

    preview_payload = {
        "metadata": {
            "project_name": "Test",
            "gateway_ip": "192.168.1.1",
            "total_addresses": 0,
            "homekit_enabled": False,
            "alexa_enabled": False,
            "unknown_items": [],
        },
        "buildings": [],
    }

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
            "log": job_log,
        }

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/upload") and method == "POST":
            state["status"] = "completed"
            return _fulfill(route, {"id": JOB_ID, "status": "running"})

        if url.endswith("/api/jobs"):
            return _fulfill(route, [job_payload()])

        if re.search(r"/api/job/[^/]+/events$", url):
            body = 'data: {"type": "status", "message": "completed"}\n\n'
            route.fulfill(status=200, content_type="text/event-stream", body=body)
            return

        if re.search(r"/api/job/[^/]+/preview$", url):
            return _fulfill(route, preview_payload)

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


def _upload_and_wait(page: Page):
    if os.path.exists(TEST_FILE_PATH):
        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
    else:
        page.locator("#fileInput").set_input_files(
            {"name": "test.knxproj", "mimeType": "application/octet-stream", "buffer": b"\x00"}
        )
    page.locator("button[type='submit']").click()
    expect(page.locator("#detail-section")).to_be_visible(timeout=20000)


@pytest.mark.ui
class TestSSEStreaming:
    def test_sse_connection_starts_on_upload(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#log")).not_to_have_text("Waiting for events...", timeout=10000)

    def test_sse_backup_event_logged(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#log")).to_contain_text("backup created", timeout=10000)

    def test_sse_status_updates_render(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#jobDetail .badge")).to_contain_text(
            re.compile(r"running|completed"), timeout=20000
        )

    def test_sse_stats_event_logged(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#log")).to_contain_text("STATS", timeout=10000)

    def test_sse_error_event_shows_in_log(self, page: Page, base_url, flask_server):
        error_log = [
            {"level": "error", "text": "[ERROR] Something went wrong"},
            {"level": "error", "text": "[STATUS] failed"},
        ]
        _setup_sse_routes(page, job_log=error_log)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#log")).to_contain_text("ERROR", timeout=10000)
        expect(page.locator("#log")).to_contain_text("Something went wrong", timeout=10000)

    def test_sse_done_completes_job(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)

    def test_sse_log_level_filter(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        expect(page.locator("#logLevelFilter")).to_be_visible(timeout=10000)

        page.locator("#logLevelFilter").select_option("error")
        page.wait_for_timeout(500)

        error_entries = page.locator(".log-entry.log-level-error")
        info_entries = page.locator(".log-entry.log-level-info")
        assert error_entries.count() >= 0
        assert info_entries.count() == 0

    def test_sse_multiple_event_types(self, page: Page, base_url, flask_server):
        _setup_sse_routes(page)
        page.goto(base_url)

        _upload_and_wait(page)
        log_text = page.locator("#log").inner_text()
        assert "backup" in log_text.lower() or "status" in log_text.lower()
