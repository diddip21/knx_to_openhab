"""End-to-end UI tests for job lifecycle (upload, deploy, rollback, rerun)."""

import json
import os
import re

import pytest
from playwright.sync_api import Page, expect

TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


def _setup_e2e_routes(page: Page):
    job_id = "job-e2e-test"
    state = {"created": False, "deployed": False, "status": "running", "rerun_count": 0}

    def job_payload():
        return {
            "id": job_id,
            "name": "E2E Test Job",
            "status": state["status"],
            "staged": True,
            "deployed": state["deployed"],
            "backups": [{"name": "backup-1", "ts": "2026-01-01"}],
            "created": 1700000000,
            "stats": {
                "openhab/items/knx.items": {
                    "before": 0,
                    "after": 5,
                    "delta": 5,
                    "added": 5,
                    "removed": 0,
                }
            },
            "log": [],
        }

    preview_payload = {
        "metadata": {
            "project_name": "E2E Project",
            "gateway_ip": "192.168.1.10",
            "total_addresses": 3,
            "homekit_enabled": False,
            "alexa_enabled": False,
            "unknown_items": [],
        },
        "buildings": [
            {
                "name": "Test Building",
                "description": "",
                "floors": [
                    {
                        "name": "Floor 1",
                        "description": "",
                        "rooms": [
                            {
                                "name": "Room A",
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

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/upload") and method == "POST":
            state["created"] = True
            state["status"] = "running"
            state["deployed"] = False
            return _fulfill(route, {"id": job_id, "status": "running"})

        if url.endswith("/api/jobs"):
            return _fulfill(route, [job_payload()] if state["created"] else [])

        if re.search(r"/api/job/[^/]+/events$", url):
            state["status"] = "completed"
            body = (
                'data: {"type": "status", "message": "running"}\n\n'
                'data: {"type": "status", "message": "completed (staged) - ready to deploy"}\n\n'
            )
            route.fulfill(status=200, content_type="text/event-stream", body=body)
            return

        if re.search(r"/api/job/[^/]+/preview$", url):
            return _fulfill(route, preview_payload)

        if re.search(r"/api/job/[^/]+/deploy$", url) and method == "POST":
            state["deployed"] = True
            return _fulfill(route, {"success": True, "message": "Deployed 1 files."})

        if re.search(r"/api/job/[^/]+/rollback$", url) and method == "POST":
            state["deployed"] = False
            return _fulfill(route, {"ok": True, "output": "restored backup-1"})

        if re.search(r"/api/job/[^/]+/rerun$", url) and method == "POST":
            state["rerun_count"] += 1
            new_id = f"job-rerun-{state['rerun_count']}"
            return _fulfill(route, {"id": new_id, "status": "queued"})

        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return _fulfill(route, job_payload())

        if re.search(r"/api/job/[^/]+$", url) and method == "DELETE":
            state["created"] = False
            return _fulfill(route, {"ok": True})

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
class TestJobLifecycleE2E:
    def test_upload_to_deploy(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()

        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)
        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)

        dialog_messages = []
        page.on("dialog", lambda d: (dialog_messages.append(d.message), d.accept()))

        page.locator(".job-item button:has-text('Deploy')").click()
        page.wait_for_timeout(1000)
        assert any("deploy" in msg.lower() for msg in dialog_messages)

    def test_rollback_after_deploy(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()
        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)

        page.on("dialog", lambda d: d.accept())

        page.locator(".job-item button:has-text('Deploy')").click()
        page.wait_for_timeout(1000)

        page.locator(".job-item button:has-text('Rollback')").click()
        expect(page.locator("#rollbackDialog[open]")).to_be_visible()
        page.locator("#rollbackDialog button:has-text('Rollback')").click()
        expect(page.locator("#rollbackStatus")).to_contain_text(
            "Rollback successful", timeout=10000
        )

    def test_delete_job_cleans_list(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        page.on("dialog", lambda d: d.accept())

        page.locator(".job-item button:has-text('Delete')").click()
        expect(page.locator(".job-item")).to_have_count(0, timeout=10000)

    def test_job_detail_for_completed_job(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()
        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)

        expect(page.locator("#detail-section")).to_be_visible()
        expect(page.locator("#log-section")).to_be_visible()
        expect(page.locator("#stats-section")).to_be_visible()

    def test_concurrent_uploads(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()
        expect(page.locator("#detail-section")).to_be_visible(timeout=20000)

        expect(page.locator(".job-item")).to_have_count(1)

    def test_job_flow_with_structure_view(self, page: Page, base_url, flask_server):
        if not os.path.exists(TEST_FILE_PATH):
            pytest.skip("Test file not found")

        _setup_e2e_routes(page)
        page.goto(base_url)

        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        page.locator("button[type='submit']").click()
        expect(page.locator("#jobDetail .badge")).to_contain_text("completed", timeout=20000)

        page.locator(".job-item button:has-text('Structure')").click()
        expect(page.locator("#preview-section")).to_be_visible(timeout=10000)
        expect(page.locator(".building-node")).to_be_visible()
