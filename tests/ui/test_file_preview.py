"""UI tests for file preview dialog (from stats table)."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

JOB_ID = "job-preview-test"


def _setup_preview_routes(page: Page):
    file_content = """Thing Thing:knx:bridge "KNX Bridge" @ "KNX" {
    Type switch : light_switch "Light Switch" [ ga="1/2/3" ]
}"""

    diff_lines = [
        {"type": "added", "line": 'Thing Thing:knx:bridge "KNX Bridge" @ "KNX" {', "curr_ln": 1},
        {
            "type": "added",
            "line": '    Type switch : light_switch "Light Switch" [ ga="1/2/3" ]',
            "curr_ln": 2,
        },
        {"type": "added", "line": "}", "curr_ln": 3},
    ]

    def job_payload():
        return {
            "id": JOB_ID,
            "name": "Preview Test Job",
            "status": "completed",
            "staged": True,
            "deployed": False,
            "backups": [],
            "created": 1700000000,
            "stats": {
                "openhab/things/knx.things": {
                    "before": 0,
                    "after": 3,
                    "delta": 3,
                    "added": 3,
                    "removed": 0,
                    "staged_path": "/tmp/staging/openhab/things/knx.things",
                    "real_path": "/tmp/openhab/things/knx.things",
                }
            },
            "log": [],
        }

    def _fulfill_json(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/jobs"):
            return _fulfill_json(route, [job_payload()])

        if re.search(r"/api/job/[^/]+/diff$", url):
            return _fulfill_json(route, {"openhab/things/knx.things": diff_lines})

        if re.search(r"/api/job/[^/]+/file/diff.*", url):
            return _fulfill_json(route, diff_lines)

        if re.search(r"/api/job/[^/]+/preview$", url):
            return _fulfill_json(
                route,
                {
                    "metadata": {
                        "project_name": "Preview Test",
                        "gateway_ip": "192.168.1.10",
                        "total_addresses": 1,
                        "homekit_enabled": False,
                        "alexa_enabled": False,
                        "unknown_items": [],
                    },
                    "buildings": [],
                },
            )

        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return _fulfill_json(route, job_payload())

        if re.search(r"/api/file/preview.*", url):
            return _fulfill_json(
                route,
                {
                    "path": "openhab/things/knx.things",
                    "content": file_content,
                    "size": 150,
                    "from_staged": True,
                },
            )

        if url.endswith("/api/services"):
            return _fulfill_json(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill_json(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill_json(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill_json(route, {})
        if url.endswith("/api/status"):
            return _fulfill_json(route, {"status": "ok"})

        return _fulfill_json(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestFilePreview:
    def _open_stats_preview(self, page: Page, base_url, flask_server):
        _setup_preview_routes(page)
        page.goto(base_url)

        page.wait_for_function("window.refreshJobs !== undefined")
        page.evaluate("refreshJobs()")
        expect(page.locator(".job-item")).to_have_count(1)

        page.locator(".job-item button:has-text('Details')").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=10000)
        expect(page.locator("#stats-section")).to_be_visible(timeout=10000)

        page.locator(".stats-table button:has-text('Preview')").first.click()

    def test_preview_from_stats_opens_dialog(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)
        expect(page.locator("#filePreviewDialog[open]")).to_be_visible(timeout=10000)

    def test_preview_final_view_shows_content(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#previewContent")).to_be_visible()
        expect(page.locator("#previewContent")).to_contain_text("Thing Thing:knx:bridge")

    def test_preview_diff_view_toggle(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#previewContent")).not_to_have_text("Loading...", timeout=10000)
        page.locator("#viewModeDiff").click()
        expect(page.locator("#diffLegend")).to_be_visible()
        expect(page.locator("#diffContent")).to_be_visible()

    def test_preview_diff_shows_additions(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#previewContent")).not_to_have_text("Loading...", timeout=10000)
        page.locator("#viewModeDiff").click()
        added_lines = page.locator(".diff-line.added")
        expect(added_lines.first).to_be_visible()
        expect(added_lines.first).to_contain_text("Thing Thing:knx:bridge")

    def test_preview_switch_back_to_final(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#previewContent")).not_to_have_text("Loading...", timeout=10000)
        page.locator("#viewModeDiff").click()
        expect(page.locator("#diffContent")).to_be_visible()

        page.locator("#viewModeFinal").click()
        expect(page.locator("#previewContent")).to_be_visible()

    def test_preview_dialog_close(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#filePreviewDialog[open]")).to_be_visible()
        page.locator("#filePreviewDialog button:has-text('Close')").click()
        expect(page.locator("#filePreviewDialog[open]")).to_have_count(0, timeout=5000)

    def test_preview_shows_filename(self, page: Page, base_url, flask_server):
        self._open_stats_preview(page, base_url, flask_server)

        expect(page.locator("#previewFileName")).to_contain_text("knx.things")
