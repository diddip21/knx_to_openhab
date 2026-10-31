"""Browser coverage for the gateway-format selector and file-only live actions."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


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

    settings = page.locator("#settings-section")
    expect(settings).to_be_visible()
    content = page.locator("#settings-content")
    if not content.is_visible():
        settings.locator(".card-header").click()
    expect(content).to_be_visible()
    expect(page.locator("#conf-items-path")).to_have_value(re.compile(r".+"), timeout=10000)


def _stub_settings_routes(
    page: Page,
    installed_version="5.0.0",
    reset_available=True,
    deployed_format="dsl",
    managed_path="things/knx.things",
    target_available=True,
    undo_available=True,
):
    project_root = Path(__file__).resolve().parents[2]
    config_data = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    config_data["things_format"] = "dsl"
    config_data["things_path"] = "openhab/things/knx.things"
    config_data["yaml_path"] = "openhab/yaml/knx.yaml"
    config_data["devices"]["gateway"]["ip_address"] = "192.0.2.42"
    calls = []

    def config_route(route):
        if route.request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(config_data))
        else:
            calls.append(("config", route.request.method, route.request.post_data_json))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"message": "Configuration updated successfully"}),
            )

    page.route("**/api/config", config_route)
    undo_done = {"value": False}

    def gateway_state_route(route):
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
                    "undo_available": undo_available and not undo_done["value"],
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
                    "saved_override": "192.0.2.42",
                }
            ),
        )

    page.route("**/api/gateway/ip**", gateway_action)
    return calls


@pytest.mark.ui
def test_format_selector_shows_migration_paths_and_openhab_compatibility(page: Page, flask_server):
    _stub_settings_routes(page, installed_version=None)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    format_select = page.locator("#conf-things-format")
    expect(format_select).to_have_value("dsl")
    expect(page.locator("#conf-yaml-path-group")).to_be_hidden()

    format_select.select_option("yaml")

    expect(page.locator("#gateway-format-warning")).to_contain_text("could not be determined")
    expect(page.locator("#conf-yaml-path-group")).to_be_visible()
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/knx.yaml")
    expect(page.locator("#gateway-migration-preview")).to_contain_text("openhab/things/knx.things")
    expect(page.locator("#gateway-migration-preview")).to_contain_text("openhab/yaml/knx.yaml")
    expect(page.locator("#gateway-migration-preview")).to_contain_text(
        "Manual edits inside the generator-owned file are backed up but not translated"
    )

    dialog_messages = []
    page.once("dialog", lambda dialog: (dialog_messages.append(dialog.message), dialog.dismiss()))
    page.get_by_role("button", name="Save & Reprocess Last Job").click()
    assert "openhab/things/knx.things" in dialog_messages[0]
    assert "openhab/yaml/knx.yaml" in dialog_messages[0]
    assert "not translated" in dialog_messages[0]


@pytest.mark.ui
def test_yaml_format_is_blocked_on_openhab_four(page: Page, flask_server):
    _stub_settings_routes(page, installed_version="4.3.6")
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    page.locator("#conf-things-format").select_option("yaml")

    expect(page.locator("#gateway-format-warning")).to_contain_text("requires OpenHAB 5.0 or newer")
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
        "Datei aktualisiert; OpenHAB-Laufzeitstatus nicht geprüft"
    )
    assert "online" not in page.locator("#gateway-action-status").inner_text().lower()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Restore ETS address").click()
    expect(page.locator("#gateway-action-status")).to_contain_text(
        "Datei aktualisiert; OpenHAB-Laufzeitstatus nicht geprüft"
    )

    gateway_urls = [
        call[0] for call in calls if isinstance(call[0], str) and "/api/gateway/ip" in call[0]
    ]
    assert gateway_urls[0].endswith("/api/gateway/ip")
    assert gateway_urls[1].endswith("/api/gateway/ip/reset")
    assert not any(call[0] == "config" and call[1] == "POST" for call in calls)
    assert not any("/rerun" in str(call[0]) for call in calls)


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

    page.locator("#conf-things-format").select_option("yaml")

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
    [("4.4.0", False), (None, False), ("5.0.0", True), ("5.1.2", True)],
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
            "deployed YAML Things file requires a known OpenHAB 5.0 or newer installation"
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
        "Datei wiederhergestellt; OpenHAB-Laufzeitstatus nicht geprüft"
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
