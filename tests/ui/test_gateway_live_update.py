"""Browser coverage for the gateway-format selector and file-only live actions."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Dialog, Page, expect


def _open_settings(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    if page.locator("input[name='username']").count() > 0:
        username = os.getenv("UI_AUTH_USER")
        password = os.getenv("UI_AUTH_PASSWORD")
        if not username or not password:
            pytest.skip("Set UI_AUTH_USER and UI_AUTH_PASSWORD to test authenticated UI")
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)
        page.click("button[type='submit']")
        expect(page.locator("#upload-section")).to_be_visible(timeout=10000)

    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    settings = page.locator("#settings-section")
    expect(settings).to_be_visible()
    content = page.locator("#settings-content")
    if not content.is_visible():
        settings.locator(".card-header").click()
    expect(content).to_be_visible()
    expect(page.locator("#configStatus")).to_contain_text("Configuration loaded", timeout=10000)


def _stub_settings_routes(
    page: Page,
    installed_version="5.2.0",
    reset_available=True,
    deployed_format="dsl",
    managed_path="things/knx.things",
    target_available=True,
    undo_available=True,
    apply_saved_override="192.0.2.42",
    save_invalidates_undo=False,
):
    project_root = Path(__file__).resolve().parents[2]
    config_data = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    config_data["output_format"] = "legacy"
    config_data["things_path"] = "openhab/things/knx.things"
    config_data["yaml_path"] = "openhab/yaml/knx.yaml"
    config_data["devices"]["gateway"]["ip_address"] = "192.0.2.42"
    config_data["devices"]["gateway"]["hardware_name"] = ["KNX IP Interface"]
    calls = []
    undo_stale = {"value": False}

    def config_route(route):
        if route.request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(config_data))
        else:
            calls.append(("config", route.request.method, route.request.post_data_json))
            if save_invalidates_undo:
                undo_stale["value"] = True
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"message": "Configuration updated successfully"}),
            )

    page.route("**/api/config", config_route)
    undo_done = {"value": False}

    def gateway_state_route(route):
        calls.append(("gateway-state", route.request.method, None))
        if not target_available:
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"error": "No usable deployed KNX Things target"}),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "things_format": deployed_format,
                    "managed_path": managed_path,
                    "active_path": "C:/temporary/demo/openhab/" + managed_path,
                    "gateway_ip": "192.0.2.42",
                    "gateway_mode": "TUNNEL",
                    "saved_override": "192.0.2.42",
                    "detected_gateway_ip": "198.51.100.10",
                    "reset_available": reset_available,
                    "undo_available": (
                        undo_available and not undo_done["value"] and not undo_stale["value"]
                    ),
                    "runtime_status": "not_checked",
                }
            ),
        )

    page.route("**/api/gateway/state", gateway_state_route)
    page.route(
        "**/api/service/openhab/version",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"installed": installed_version, "supported": bool(installed_version)}),
        ),
    )

    def gateway_action(route):
        calls.append((route.request.url, route.request.method, route.request.post_data_json))
        reset = route.request.url.endswith("/reset")
        undo = route.request.url.endswith("/undo")
        if undo:
            undo_done["value"] = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "success": True,
                    "gateway_ip": (
                        None if reset else (route.request.post_data_json or {}).get("ip_address")
                    ),
                    "gateway_mode": "ROUTER" if reset else "TUNNEL",
                    "message": "KNX gateway configuration file updated; OpenHAB runtime status was not checked.",
                    "runtime_status": "not_checked",
                    "undo_available": not undo,
                    "saved_override": apply_saved_override,
                }
            ),
        )

    page.route("**/api/gateway/ip**", gateway_action)
    return calls


def _stub_job_transition_routes(page: Page, transition: str):
    _stub_settings_routes(page)
    state = {
        "available": True,
        "things_format": "dsl",
        "managed_path": "things/initial-knx.things",
    }
    job = {
        "id": "gateway-transition-job",
        "name": "Gateway transition job",
        "status": "completed",
        "staged": True,
        "deployed": transition in ("rollback", "delete"),
        "backups": [{"name": "backup-current", "ts": "2026-01-01"}],
        "created": 1700000000,
        "stats": {},
        "log": [],
    }
    state_requests = []

    def fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def gateway_state_route(route):
        state_requests.append(dict(state))
        if not state["available"]:
            return fulfill(route, {"error": "No usable deployed KNX Things target"}, status=409)
        fulfill(
            route,
            {
                "things_format": state["things_format"],
                "managed_path": state["managed_path"],
                "gateway_ip": "192.0.2.42",
                "gateway_mode": "TUNNEL",
                "saved_override": "192.0.2.42",
                "detected_gateway_ip": "198.51.100.10",
                "reset_available": True,
                "undo_available": True,
                "runtime_status": "not_checked",
            },
        )

    def jobs_route(route):
        fulfill(route, [dict(job)])

    def job_route(route):
        if route.request.method == "DELETE":
            deleting_active_job = job["deployed"]
            job["deployed"] = False
            if deleting_active_job:
                state["available"] = False
            fulfill(route, {"ok": True})
            return
        fulfill(route, dict(job))

    def deploy_route(route):
        job["deployed"] = True
        state.update(
            things_format="yaml",
            managed_path="yaml/deployed-knx.yaml",
        )
        fulfill(route, {"success": True, "message": "Deployed successfully"})

    def rollback_route(route):
        job["deployed"] = False
        state["available"] = False
        fulfill(route, {"ok": True, "output": "restored backup-current"})

    page.route("**/api/gateway/state", gateway_state_route)
    page.route("**/api/jobs", jobs_route)
    page.route("**/api/job/gateway-transition-job", job_route)
    page.route("**/api/job/gateway-transition-job/deploy", deploy_route)
    page.route("**/api/job/gateway-transition-job/rollback", rollback_route)
    return state_requests


@pytest.mark.ui
def test_format_selector_shows_migration_paths_and_openhab_compatibility(page: Page, flask_server):
    _stub_settings_routes(page, installed_version=None)
    _open_settings(page, flask_server)

    format_select = page.locator("#conf-output-format")
    expect(format_select).to_have_value("legacy")
    expect(page.locator("#yaml-path-group")).to_be_hidden()

    format_select.select_option("yaml")

    expect(page.locator("#gateway-format-warning")).to_contain_text("could not be determined")
    expect(page.locator("#yaml-path-group")).to_be_visible()
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/knx.yaml")
    expect(page.locator("#gateway-migration-preview")).to_contain_text("things/knx.things")
    expect(page.locator("#gateway-migration-preview")).to_contain_text("openhab/yaml/knx.yaml")
    expect(page.locator("#gateway-migration-preview")).to_contain_text(
        "manual files remain untouched"
    )

    dialog_messages: list[str] = []

    def dismiss_migration_dialog(dialog: Dialog) -> None:
        dialog_messages.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", dismiss_migration_dialog)
    page.get_by_role("button", name="Save & Reprocess Last Job").click()
    assert "things/knx.things" in dialog_messages[0]
    assert "openhab/yaml/knx.yaml" in dialog_messages[0]
    assert "manual files are not changed" in dialog_messages[0]


@pytest.mark.ui
def test_yaml_format_is_blocked_below_openhab_5_2(page: Page, flask_server):
    _stub_settings_routes(page, installed_version="5.1.12")
    _open_settings(page, flask_server)

    page.locator("#conf-output-format").select_option("yaml")

    expect(page.locator("#gateway-format-warning")).to_contain_text("requires OpenHAB 5.2 or newer")
    expect(page.get_by_role("button", name="Save & Reprocess Last Job")).to_be_disabled()


@pytest.mark.ui
def test_live_apply_and_reset_use_dedicated_file_only_routes(page: Page, flask_server):
    calls = _stub_settings_routes(page, reset_available=True)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    expect(page.locator("#gateway-file-state")).to_contain_text("192.0.2.42")
    expect(page.locator("#gateway-file-state")).to_contain_text("Runtime status not checked")
    expect(page.locator("#gateway-reset-ip")).to_be_enabled()
    page.locator("#conf-gateway-ip").fill("2001:db8::1")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Apply IP to live OpenHAB file").click()
    expect(page.locator("#gateway-action-status")).to_contain_text(
        "File updated; OpenHAB runtime status not checked"
    )
    assert "online" not in page.locator("#gateway-action-status").inner_text().lower()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Restore ETS address").click()
    expect(page.locator("#gateway-action-status")).to_contain_text(
        "File updated; OpenHAB runtime status not checked"
    )

    gateway_urls = [
        call[0] for call in calls if isinstance(call[0], str) and "/api/gateway/ip" in call[0]
    ]
    assert gateway_urls[0].endswith("/api/gateway/ip")
    assert gateway_urls[1].endswith("/api/gateway/ip/reset")
    assert not any(call[0] == "config" and call[1] == "POST" for call in calls)
    assert not any("/rerun" in str(call[0]) for call in calls)


@pytest.mark.ui
def test_live_apply_saves_backend_canonical_ipv6_override(page: Page, flask_server):
    calls = _stub_settings_routes(page, apply_saved_override="2001:db8::1")
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    page.locator("#conf-gateway-ip").fill("2001:0db8::1")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Apply IP to live OpenHAB file").click()

    expect(page.locator("#conf-gateway-ip")).to_have_value("2001:db8::1")
    expect(page.locator("#gateway-action-status")).to_contain_text(
        "File updated; OpenHAB runtime status not checked"
    )
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_path = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
        screenshot_path.mkdir(parents=True, exist_ok=True)
        page.locator("#tab-devices").screenshot(
            path=str(screenshot_path / "gateway-ip-canonicalized.png")
        )

    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")

    saved_configs = [call[2] for call in calls if call[0] == "config" and call[1] == "POST"]
    assert saved_configs
    assert saved_configs[-1]["devices"]["gateway"]["ip_address"] == "2001:db8::1"


@pytest.mark.ui
def test_live_target_display_uses_last_deployed_path_not_pending_format_or_absolute_path(
    page: Page, flask_server
):
    _stub_settings_routes(
        page,
        deployed_format="dsl",
        managed_path="things/deployed-knx.things",
    )
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    state = page.locator("#gateway-file-state")
    expect(state).to_contain_text("DSL file things/deployed-knx.things")
    expect(state).not_to_contain_text("C:/temporary/demo")

    page.get_by_role("button", name="General").click()
    page.locator("#conf-output-format").select_option("yaml")
    page.get_by_role("button", name="Devices").click()

    expect(state).to_contain_text("DSL file things/deployed-knx.things")
    expect(state).not_to_contain_text("yaml/knx.yaml")


@pytest.mark.ui
def test_all_live_actions_are_disabled_without_a_deployed_target(page: Page, flask_server):
    _stub_settings_routes(page, target_available=False)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    expect(page.locator("#gateway-apply-ip")).to_be_disabled()
    expect(page.locator("#gateway-reset-ip")).to_be_disabled()
    expect(page.get_by_role("button", name="Undo last live change")).to_be_disabled()
    expect(page.locator("#gateway-live-warning")).to_contain_text(
        "no usable successfully deployed KNX Things target"
    )


@pytest.mark.ui
@pytest.mark.parametrize(
    ("installed_version", "should_enable"),
    [
        ("4.4.0", False),
        (None, False),
        ("5.0.0", False),
        ("5.1.2", False),
        ("5.2.0", True),
        ("5.2.7", True),
    ],
)
def test_yaml_deployed_live_actions_follow_installed_openhab_compatibility(
    page: Page, flask_server, installed_version, should_enable
):
    _stub_settings_routes(
        page,
        installed_version=installed_version,
        deployed_format="yaml",
        managed_path="yaml/deployed-knx.yaml",
    )
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    controls = [
        page.locator("#gateway-apply-ip"),
        page.locator("#gateway-reset-ip"),
        page.get_by_role("button", name="Undo last live change"),
    ]
    for control in controls:
        if should_enable:
            expect(control).to_be_enabled()
        else:
            expect(control).to_be_disabled()
    if should_enable:
        expect(page.locator("#gateway-live-warning")).to_be_hidden()
    else:
        expect(page.locator("#gateway-live-warning")).to_contain_text(
            "deployed YAML model requires a known OpenHAB 5.2 or newer installation"
        )


@pytest.mark.ui
def test_undo_uses_only_undo_route_and_disables_after_success(page: Page, flask_server):
    calls = _stub_settings_routes(page, undo_available=True)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    undo_button = page.get_by_role("button", name="Undo last live change")
    expect(undo_button).to_be_enabled()

    page.once("dialog", lambda dialog: dialog.accept())
    undo_button.click()

    expect(page.locator("#gateway-action-status")).to_contain_text(
        "File restored; OpenHAB runtime status not checked"
    )
    expect(undo_button).to_be_disabled()
    assert "online" not in page.locator("#gateway-action-status").inner_text().lower()
    gateway_urls = [
        call[0] for call in calls if isinstance(call[0], str) and "/api/gateway/ip" in call[0]
    ]
    assert gateway_urls == ["http://127.0.0.1/api/gateway/ip/undo"] or (
        len(gateway_urls) == 1 and gateway_urls[0].endswith("/api/gateway/ip/undo")
    )


@pytest.mark.ui
def test_reset_is_disabled_without_successfully_deployed_ets_source(page: Page, flask_server):
    _stub_settings_routes(page, reset_available=False)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    expect(page.get_by_role("button", name="Restore ETS address")).to_be_disabled()


@pytest.mark.ui
def test_successful_deploy_refreshes_gateway_target_state(page: Page, flask_server):
    state_requests = _stub_job_transition_routes(page, "deploy")
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    gateway_state = page.locator("#gateway-file-state")
    expect(gateway_state).to_contain_text("things/initial-knx.things")

    page.on("dialog", lambda dialog: dialog.accept())
    page.locator(".job-item button:has-text('Deploy')").click()

    expect(gateway_state).to_contain_text("YAML file yaml/deployed-knx.yaml")
    assert len(state_requests) >= 2
    assert state_requests[-1] == {
        "available": True,
        "things_format": "yaml",
        "managed_path": "yaml/deployed-knx.yaml",
    }


@pytest.mark.ui
def test_successful_rollback_refreshes_gateway_target_availability(page: Page, flask_server):
    state_requests = _stub_job_transition_routes(page, "rollback")
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    gateway_state = page.locator("#gateway-file-state")
    expect(gateway_state).to_contain_text("things/initial-knx.things")
    expect(page.locator("#gateway-apply-ip")).to_be_enabled()

    page.locator(".job-item button:has-text('Rollback')").click()
    expect(page.locator("#rollbackDialog")).to_be_visible()
    page.locator("#rollbackDialog button:has-text('Rollback')").click()

    expect(gateway_state).to_contain_text("No usable deployed KNX Things target")
    expect(page.locator("#gateway-apply-ip")).to_be_disabled()
    assert len(state_requests) >= 2
    assert state_requests[-1]["available"] is False
    expect(page.locator("#rollbackDialog")).to_be_hidden(timeout=5000)
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_path = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
        screenshot_path.mkdir(parents=True, exist_ok=True)
        page.locator("#tab-devices").screenshot(
            path=str(screenshot_path / "gateway-state-after-rollback.png")
        )


@pytest.mark.ui
def test_successful_active_job_deletion_refreshes_gateway_availability(page: Page, flask_server):
    state_requests = _stub_job_transition_routes(page, "delete")
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    gateway_state = page.locator("#gateway-file-state")
    expect(gateway_state).to_contain_text("things/initial-knx.things")
    expect(page.locator("#gateway-apply-ip")).to_be_enabled()
    expect(page.locator("#gateway-reset-ip")).to_be_enabled()
    expect(page.locator("#gateway-undo-ip")).to_be_enabled()

    page.on("dialog", lambda dialog: dialog.accept())
    page.locator(".job-item button:has-text('Delete')").click()

    expect(gateway_state).to_contain_text("No usable deployed KNX Things target")
    expect(page.locator("#gateway-apply-ip")).to_be_disabled()
    expect(page.locator("#gateway-reset-ip")).to_be_disabled()
    expect(page.locator("#gateway-undo-ip")).to_be_disabled()
    assert len(state_requests) >= 2
    assert state_requests[-1]["available"] is False
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_path = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
        screenshot_path.mkdir(parents=True, exist_ok=True)
        page.locator("#tab-devices").screenshot(
            path=str(screenshot_path / "gateway-state-after-job-delete.png")
        )


@pytest.mark.ui
def test_config_save_refreshes_gateway_undo_availability(page: Page, flask_server):
    calls = _stub_settings_routes(page, save_invalidates_undo=True)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    expect(page.locator("#gateway-undo-ip")).to_be_enabled()
    initial_state_requests = len([call for call in calls if call[0] == "gateway-state"])

    page.locator("#conf-gateway-ip").fill("192.0.2.99")
    page.get_by_role("button", name="Save Config").click()

    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
    expect(page.locator("#gateway-undo-ip")).to_be_disabled()
    assert len([call for call in calls if call[0] == "gateway-state"]) == initial_state_requests + 1
    saved_configs = [call[2] for call in calls if call[0] == "config" and call[1] == "POST"]
    assert saved_configs[-1]["devices"]["gateway"]["ip_address"] == "192.0.2.99"
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_path = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
        screenshot_path.mkdir(parents=True, exist_ok=True)
        page.locator("#tab-devices").screenshot(
            path=str(screenshot_path / "gateway-undo-disabled-after-config-save.png")
        )


@pytest.mark.ui
def test_issue40_documentation_views_use_example_data(page: Page, flask_server):
    """Capture the real UI with a documentation IP and synthetic KNX addresses."""
    _stub_settings_routes(page)
    page.set_viewport_size({"width": 1440, "height": 900})
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()
    page.locator("#conf-gateway-ip").fill("192.0.2.45")
    expect(page.locator("#conf-gateway-ip")).to_have_value("192.0.2.45")

    screenshot_dir = Path(__file__).resolve().parents[2] / "test-results"
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_dir / "issue-40-gateway-ip-settings.png"))

    example_things = (
        'Bridge knx:ip:bridge [\n'
        '    type="TUNNEL",\n'
        '    ipAddress="192.0.2.45",\n'
        '    portNumber=3671\n'
        '] {\n'
        '    Thing device demo [\n'
        '        Type switch : i_demo_switch "Demo switch" [ ga="1/1/1" ]\n'
        '    ]\n'
        '}\n'
    )
    page.route(
        "**/api/file/preview?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"content": example_things, "size": len(example_things)}),
        ),
    )
    page.evaluate("previewFile('knx.things')")
    dialog = page.locator("#filePreviewDialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('ipAddress="192.0.2.45"')
    expect(dialog).to_contain_text('ga="1/1/1"')
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        page.screenshot(path=str(screenshot_dir / "issue-40-generated-knx-things.png"))
