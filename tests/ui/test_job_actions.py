import json
import re

import pytest
from playwright.sync_api import Page, expect

JOB_ID = "job-1"


def _setup_job_routes(page: Page):
    jobs = [
        {
            "id": JOB_ID,
            "name": "Test Job",
            "status": "completed",
            "staged": True,
            "deployed": False,
            "backups": [{"name": "backup-1", "ts": "2026-02-04"}],
            "created": 1700000000,
            "stats": {},
        }
    ]

    preview_payload = {
        "metadata": {
            "project_name": "Demo Project",
            "gateway_ip": "192.168.1.2",
            "total_addresses": 1,
            "homekit_enabled": False,
            "alexa_enabled": True,
            "unknown_items": [],
        },
        "buildings": [
            {
                "name": "HQ",
                "description": "",
                "floors": [
                    {
                        "name": "1",
                        "description": "",
                        "rooms": [
                            {
                                "name": "Office",
                                "description": "",
                                "address_count": 1,
                                "device_count": 1,
                                "addresses": [{"Group name": "Light", "Address": "1/2/3"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    diffs_payload = {
        "openhab/items.items": [{"type": "added", "line": "Switch test", "curr_ln": 1}]
    }

    def _job_detail():
        job = dict(jobs[0])
        job.setdefault("log", [])
        return job

    def _fulfill(route, data, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(data),
        )

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/jobs"):
            return _fulfill(route, jobs)
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if re.search(r"/api/job/[^/]+/deploy$", url) and method == "POST":
            jobs[0]["deployed"] = True
            return _fulfill(route, {"success": True, "message": "OK"})
        if re.search(r"/api/job/[^/]+/rollback$", url) and method == "POST":
            return _fulfill(route, {"ok": True, "output": "Rollback done"})
        if re.search(r"/api/job/[^/]+/diff$", url):
            return _fulfill(route, diffs_payload)
        if re.search(r"/api/job/[^/]+/preview$", url):
            return _fulfill(route, preview_payload)
        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return _fulfill(route, _job_detail())
        if re.search(r"/api/job/[^/]+$", url) and method == "DELETE":
            jobs.clear()
            return _fulfill(route, {"ok": True})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)

    return jobs


@pytest.mark.usefixtures("server")
class TestJobActions:
    def test_job_action_buttons_render(self, page: Page, base_url):
        _setup_job_routes(page)
        page.goto(base_url)

        expect(page.locator(".job-item")).to_have_count(1)
        expect(page.locator(".job-item button:has-text('Structure')")).to_be_visible()
        expect(page.locator(".job-item button:has-text('Diff')")).to_be_visible()
        expect(page.locator(".job-item button:has-text('Deploy')")).to_be_visible()
        expect(page.locator(".job-item button:has-text('Rollback')")).to_be_visible()
        expect(page.locator(".job-item button:has-text('Delete')")).to_be_visible()

    def test_job_action_diff_and_structure(self, page: Page, base_url):
        _setup_job_routes(page)
        page.goto(base_url)

        expect(page.locator(".job-item")).to_have_count(1)
        page.locator(".job-item button:has-text('Diff')").click()

        diff_dialog = page.locator("#filePreviewDialog[open]")
        expect(diff_dialog).to_be_visible()
        expect(page.locator("#previewFileName")).to_have_text(f"Diff für Job {JOB_ID}")
        expect(page.locator("#diffContent")).to_contain_text("Switch test")

        page.locator("#filePreviewDialog button:has-text('Close')").click()

        page.locator(".job-item button:has-text('Structure')").click()
        expect(page.locator("#preview-section")).to_be_visible()
        expect(page.locator("#status")).to_contain_text("✓ Structure loaded from job history")

    def test_job_action_deploy_rollback_delete(self, page: Page, base_url):
        _setup_job_routes(page)
        page.goto(base_url)

        dialog_messages = []

        def handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            dialog.accept()

        page.on("dialog", handle_dialog)

        page.locator(".job-item button:has-text('Deploy')").click()
        expect(page.locator(".job-item button:has-text('Deploy')")).to_have_count(0)
        page.wait_for_timeout(100)
        assert any("Really deploy" in msg for msg in dialog_messages)
        assert any("Successfully deployed" in msg for msg in dialog_messages)

        page.locator(".job-item button:has-text('Rollback')").click()
        rollback_dialog = page.locator("#rollbackDialog[open]")
        expect(rollback_dialog).to_be_visible()
        page.locator("#rollbackDialog button:has-text('Rollback')").click()
        expect(page.locator("#rollbackStatus")).to_contain_text("✓ Rollback successful")

        page.locator(".job-item button:has-text('Delete')").click()
        expect(page.locator(".job-item")).to_have_count(0)
        assert any("Delete this job" in msg for msg in dialog_messages)
