"""Full browser journey against a real, filesystem-isolated Web UI server."""

import json
import os
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import Page, expect

TEST_PROJECT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


def _emulate_host_adapters(page: Page, calls: list[tuple[str, str]]):
    """Stub only OS/package operations; all app routes stay connected to Flask."""

    def service_route(route):
        request = route.request
        path = urlsplit(request.url).path
        calls.append((request.method, path))

        if path.endswith("/updates/status"):
            payload = {"state": "idle", "action": None, "message": "No package operation"}
        elif path.endswith("/restart"):
            payload = {"ok": True, "output": "Restart simulated by the browser emulator"}
        elif path.endswith("/status"):
            payload = {"active": True, "status": "active", "uptime_str": "active since emulator"}
        elif path.endswith("/version"):
            payload = {
                "supported": True,
                "installed": "4.3.2",
                "candidate": "4.3.3",
                "update_available": True,
                "message": "Emulated package metadata",
            }
        elif path.endswith("/updates/refresh") or "/updates/" in path:
            payload = {"ok": True, "message": "Package operation simulated"}
        else:
            payload = {"error": "Unexpected emulator service request"}
            return route.fulfill(
                status=404, content_type="application/json", body=json.dumps(payload)
            )

        return route.fulfill(
            status=202 if request.method == "POST" and "/updates/" in path else 200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def version_check_route(route):
        calls.append((route.request.method, "/api/version/check"))
        return route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "update_available": True,
                    "current_commit": "local-test",
                    "current_message": "Emulator build",
                    "current_date": "2026-11-06T10:00:00Z",
                    "latest_commit": "remote-test",
                    "latest_message": "Simulated update",
                    "latest_author": "Test Emulator",
                    "latest_date": "2026-11-06T11:00:00Z",
                }
            ),
        )

    def cloud_route(route):
        calls.append((route.request.method, "/api/openhab/cloud-info"))
        return route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"uuid": None, "secret": None}),
        )

    page.route("**/api/service/**", service_route)
    page.route("**/api/version/check", version_check_route)
    page.route("**/api/openhab/cloud-info", cloud_route)


@pytest.mark.slow
@pytest.mark.timeout(300)
@pytest.mark.skipif(
    os.name == "nt",
    reason="The isolated deployment policy uses POSIX paths; this full-stack run targets Linux CI.",
)
def test_complete_webapp_journey_in_isolated_emulator(page: Page, emulator_server):
    """Exercise real parsing, staging, previews, settings, deployment and rollback."""
    assert os.path.isfile(TEST_PROJECT), f"Required ETS fixture is missing: {TEST_PROJECT}"

    adapter_calls: list[tuple[str, str]] = []
    _emulate_host_adapters(page, adapter_calls)
    page.set_default_timeout(15000)
    page.goto(emulator_server["base_url"])
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")

    # The service and app updater screens use emulated host adapters, so this
    # test never runs systemctl, apt, or the self-update script.
    expect(page.locator("#servicesList .service-item")).to_have_count(2, timeout=30000)
    with page.expect_response(
        lambda response: response.url.endswith("/api/version/check")
        and response.request.method == "GET"
    ):
        page.locator("#versionBadge").click()
    expect(page.locator("#updateDialog")).to_be_visible()
    expect(page.locator("#dialogLatestCommit")).to_have_text("remote-test")
    page.locator("#updateDialog button[aria-label='Close dialog']").click()

    with page.expect_response(
        lambda response: response.url.endswith("/api/service/restart")
        and response.request.method == "POST"
    ):
        page.locator("#servicesList .service-item").first.locator(".restart-btn").click()
    with page.expect_response(
        lambda response: response.url.endswith("/api/service/updates/refresh")
        and response.request.method == "POST"
    ):
        page.locator("#refreshPackagesBtn").click()
    expect(page.locator("#refreshPackagesBtn")).to_be_enabled(timeout=15000)
    assert ("POST", "/api/service/restart") in adapter_calls
    assert ("POST", "/api/service/updates/refresh") in adapter_calls

    # Upload goes through Flask validation, the real xknxproject parser and the
    # generator worker. No API routes for the actual application workflow are mocked.
    page.locator("#fileInput").set_input_files(TEST_PROJECT)
    with page.expect_response(
        lambda response: response.url.endswith("/api/upload") and response.request.method == "POST"
    ) as upload_response:
        page.locator("button[type='submit']").click()
    assert upload_response.value.status == 201
    job_id = upload_response.value.json()["id"]

    expect(page.locator("#detail-section")).to_be_visible(timeout=30000)
    expect(page.locator("#jobDetail .badge")).to_contain_text("Completed", timeout=180000)
    expect(page.locator("#stats-section")).to_be_visible()
    expect(page.locator("#stats table tr").nth(1)).to_be_visible()

    job_response = requests.get(f"{emulator_server['base_url']}/api/job/{job_id}", timeout=10)
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "completed"
    assert job["staged"] is True
    assert job["openhab_root"] == str(emulator_server["openhab_root"])
    assert job["stats"]

    # Cached structure preview and staged output diff/file preview are real API calls.
    with page.expect_response(lambda response: response.url.endswith(f"/api/job/{job_id}/preview")):
        page.locator(".job-item").get_by_role("button", name="Structure").click()
    expect(page.locator("#preview-section")).to_be_visible()
    expect(page.locator(".building-node")).to_be_visible()

    page.locator(".job-item").get_by_role("button", name="Diff").click()
    expect(page.locator("#filePreviewDialog[open]")).to_be_visible()
    expect(page.locator("#diffContent")).not_to_be_empty()
    page.evaluate("document.getElementById('filePreviewDialog').close()")

    page.locator("#stats table button").first.click()
    expect(page.locator("#filePreviewDialog[open]")).to_be_visible()
    expect(page.locator("#previewContent")).not_to_be_empty(timeout=15000)
    page.evaluate("document.getElementById('filePreviewDialog').close()")

    # Saving one setting must preserve sibling generator configuration.
    page.locator("#settings-section .card-header").click()
    expect(page.locator("#settings-content")).to_be_visible()
    expect(page.locator("#conf-unknown-floor")).to_have_value("unknown", timeout=15000)
    page.locator("#conf-unknown-floor").fill("Emulator Floor")
    page.locator("button[onclick='saveConfig(false)']").click()
    expect(page.locator("#configStatus")).to_contain_text("saved", timeout=15000)
    saved_config = requests.get(f"{emulator_server['base_url']}/api/config", timeout=10).json()
    assert saved_config["general"]["unknown_floorname"] == "Emulator Floor"
    assert saved_config["items_path"] == str(
        emulator_server["openhab_root"] / "items" / "knx.items"
    ).replace("\\", "/")
    assert saved_config["output_format"] == "legacy"

    # Deploy writes only under tmp_path; rollback restores the baseline files.
    with page.expect_response(
        lambda response: response.url.endswith(f"/api/job/{job_id}/deploy")
        and response.request.method == "POST"
    ) as deploy_response:
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".job-item").get_by_role("button", name="Deploy").click()
    deploy_result = deploy_response.value.json()
    assert deploy_response.value.status == 200, (
        f"Deploy failed: {deploy_result}\n"
        f"Isolated Flask server output:\n{''.join(emulator_server['server_output'])}"
    )
    assert deploy_result["success"] is True, deploy_result

    items_file = emulator_server["openhab_root"] / "items" / "knx.items"
    things_file = emulator_server["openhab_root"] / "things" / "knx.things"
    assert items_file.is_file() and items_file.stat().st_size > 0
    assert things_file.is_file() and things_file.stat().st_size > 0
    deployed_job = requests.get(
        f"{emulator_server['base_url']}/api/job/{job_id}", timeout=10
    ).json()
    assert deployed_job["deployed"] is True
    assert deployed_job["backups"]

    page.locator(".job-item").get_by_role("button", name="Rollback").click()
    expect(page.locator("#rollbackDialog[open]")).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith(f"/api/job/{job_id}/rollback")
        and response.request.method == "POST"
    ):
        page.locator("#rollbackDialog button:has-text('Rollback')").click()
    expect(page.locator("#rollbackStatus")).to_contain_text("Rollback successful", timeout=15000)
    assert items_file.read_text(encoding="utf-8") == "# emulator baseline\n"
    assert things_file.read_text(encoding="utf-8") == "# emulator baseline\n"

    with page.expect_response(
        lambda response: response.url.endswith(f"/api/job/{job_id}")
        and response.request.method == "DELETE"
    ):
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator(".job-item").get_by_role("button", name="Delete").click()
    expect(page.locator(".job-item")).to_have_count(0, timeout=15000)
    assert requests.get(f"{emulator_server['base_url']}/api/jobs", timeout=10).json() == []
