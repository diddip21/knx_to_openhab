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


def _stub_settings_routes(page: Page, installed_version="5.0.0", reset_available=True):
    project_root = Path(__file__).resolve().parents[2]
    config_data = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    config_data["things_format"] = "dsl"
    config_data["things_path"] = "openhab/things/knx.things"
    config_data["yaml_path"] = "openhab/yaml/knx.yaml"
    config_data["devices"]["gateway"]["ip_address"] = "192.168.1.10"
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
    page.route(
        "**/api/gateway/state",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "things_format": "dsl",
                    "active_path": "openhab/things/knx.things",
                    "gateway_ip": "192.168.1.10",
                    "gateway_mode": "TUNNEL",
                    "saved_override": "192.168.1.10",
                    "detected_gateway_ip": "192.168.1.5",
                    "reset_available": reset_available,
                    "runtime_status": "not_checked",
                }
            ),
        ),
    )
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

    expect(page.locator("#gateway-file-state")).to_contain_text("192.168.1.10")
    expect(page.locator("#gateway-file-state")).to_contain_text("Runtime status not checked")
    expect(page.locator("#gateway-reset-ip")).to_be_enabled()
    page.locator("#conf-gateway-ip").fill("2001:db8::1")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Apply IP to live OpenHAB file").click()
    expect(page.locator("#gateway-action-status")).to_contain_text(
        "Datei aktualisiert; OpenHAB-Laufzeitstatus nicht geprüft"
    )

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
def test_reset_is_disabled_without_successfully_deployed_ets_source(page: Page, flask_server):
    _stub_settings_routes(page, reset_available=False)
    _open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    expect(page.get_by_role("button", name="Restore ETS address")).to_be_disabled()
