import json
import os
import re

import pytest
from playwright.sync_api import Page, expect

TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


def _setup_upload_routes(page: Page):
    job_id = "job-12345678"
    stats_payload = {
        "openhab/items.items": {
            "before": 0,
            "after": 1,
            "delta": 1,
            "added": 1,
            "removed": 0,
        }
    }

    state = {
        "created": False,
        "events_requested": False,
        "status": "running",
        "stats": {},
    }

    def job_payload():
        return {
            "id": job_id,
            "name": "Demo Project",
            "status": state["status"],
            "staged": True,
            "deployed": False,
            "backups": [{"name": "backup-1", "ts": "2026-02-08"}],
            "created": 1700000000,
            "stats": state["stats"],
            "log": [],
        }

    def fulfill(route, data, status=200, content_type="application/json"):
        route.fulfill(status=status, content_type=content_type, body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/upload") and method == "POST":
            state["created"] = True
            state["status"] = "running"
            state["stats"] = {}
            return fulfill(route, {"id": job_id, "status": "running"})

        if url.endswith("/api/jobs"):
            jobs = [job_payload()] if state["created"] else []
            return fulfill(route, jobs)

        if re.search(r"/api/job/[^/]+/events$", url):
            state["events_requested"] = True
            # Mark job as completed for subsequent status fetches
            state["status"] = "completed"
            state["stats"] = stats_payload
            sse_body = "\n".join(
                [
                    "data: {\"type\": \"status\", \"message\": \"running\"}",
                    "",
                    "data: {\"type\": \"status\", \"message\": \"completed\"}",
                    "",
                ]
            )
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=sse_body,
            )
            return

        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return fulfill(route, job_payload())

        if url.endswith("/api/services"):
            return fulfill(route, [])

        if re.search(r"/api/service/.*/status$", url):
            return fulfill(route, {"active": True, "status": "active"})

        if url.endswith("/api/version"):
            return fulfill(route, {"commit_short": "abc123"})

        if url.endswith("/api/version/check"):
            return fulfill(route, {"update_available": False})

        if url.endswith("/api/config"):
            return fulfill(route, {})

        if url.endswith("/api/status"):
            return fulfill(route, {"status": "ok"})

        return fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
@pytest.mark.usefixtures("flask_server")
def test_upload_job_lifecycle_happy_path(page: Page, base_url):
    """Upload flow + job lifecycle with mocked backend."""
    if not os.path.exists(TEST_FILE_PATH):
        pytest.skip(f"Test file not found: {TEST_FILE_PATH}")

    _setup_upload_routes(page)

    page.goto(base_url)

    file_input = page.locator("#fileInput")
    expect(file_input).to_be_visible()
    file_input.set_input_files(TEST_FILE_PATH)

    page.locator("button[type='submit']").click()

    status_div = page.locator("#status")
    expect(status_div).to_contain_text(
        re.compile(r"Processing started|File uploaded, job started|Job completed"),
        timeout=20000,
    )

    expect(page.locator("#detail-section")).to_be_visible(timeout=20000)
    expect(page.locator("#jobDetail .badge")).to_contain_text(
        re.compile(r"running|completed"), timeout=20000
    )

    expect(page.locator("#jobs .job-item")).to_have_count(1)
    expect(page.locator("#jobs .job-item .job-status")).to_contain_text(
        re.compile(r"running|completed")
    )

    expect(status_div).to_contain_text("Job completed", timeout=20000)
    expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)
    expect(page.locator("#stats")).to_contain_text("openhab/items.items", timeout=20000)
