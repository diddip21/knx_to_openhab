"""UI tests for settings/config tabs and save actions."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "logihome"


def ensure_authenticated(page: Page, base_url: str) -> None:
    page.goto(base_url)
    if page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", DEFAULT_USERNAME)
        page.fill("input[name='password']", DEFAULT_PASSWORD)
        page.click("button[type='submit']")
        expect(page.locator("#upload-section")).to_be_visible(timeout=10000)


def open_settings(page: Page, base_url: str) -> None:
    ensure_authenticated(page, base_url)

    settings_section = page.locator("#settings-section")
    expect(settings_section).to_be_visible()

    settings_content = page.locator("#settings-content")
    if not settings_content.is_visible():
        settings_section.locator(".card-header").click()
    expect(settings_content).to_be_visible()

    items_input = page.locator("#conf-items-path")
    expect(items_input).to_be_visible()
    expect(items_input).to_have_value(re.compile(r".+"), timeout=10000)


@pytest.mark.ui
def test_settings_tabs_switch(page: Page, flask_server):
    open_settings(page, flask_server)

    tab_pairs = [
        ("General", "#tab-general"),
        ("Devices", "#tab-devices"),
        ("Mappings", "#tab-mappings"),
        ("Definitions", "#tab-definitions"),
        ("Advanced", "#tab-advanced"),
    ]

    for tab_name, tab_selector in tab_pairs:
        page.get_by_role("button", name=tab_name).click()
        tab_content = page.locator(tab_selector)
        expect(tab_content).to_have_class(re.compile(r"active"))
        expect(tab_content).to_be_visible()


@pytest.mark.ui
def test_save_config_action_updates_value(page: Page, flask_server):
    open_settings(page, flask_server)

    items_input = page.locator("#conf-items-path")
    original_value = items_input.input_value()
    new_value = f"{original_value}.ui-test"

    items_input.fill(new_value)
    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")

    page.get_by_role("button", name="Reload Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration loaded")
    expect(items_input).to_have_value(new_value)

    items_input.fill(original_value)
    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")


@pytest.mark.ui
def test_save_and_reprocess_requires_job(page: Page, flask_server):
    open_settings(page, flask_server)

    dialog_messages = {}

    def handle_dialog(dialog):
        dialog_messages["message"] = dialog.message
        dialog.accept()

    page.once("dialog", handle_dialog)
    page.get_by_role("button", name="Save & Reprocess Last Job").click()

    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
    assert "No job selected" in dialog_messages.get("message", "")


@pytest.mark.ui
def test_gateway_ip_round_trip_preserves_other_device_settings(page: Page, flask_server):
    """Saving the new setting must retain existing and future device configuration."""
    config_path = Path(__file__).resolve().parents[2] / "config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["devices"]["gateway"]["ip_address"] = "192.168.1.10"
    config_data["devices"]["gateway"]["transport_mode"] = "tunnel"
    config_data["devices"]["future_device"] = {"hardware_name": ["Future Device"]}
    saved_payload = {}

    def config_route(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(config_data),
            )
            return
        if request.method == "POST":
            saved_payload.update(request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"message": "Configuration updated successfully"}),
            )
            return
        route.fulfill(status=405, body="Method not allowed")

    page.route("**/api/config", config_route)
    open_settings(page, flask_server)
    page.get_by_role("button", name="Devices").click()

    gateway_ip = page.locator("#conf-gateway-ip")
    expect(gateway_ip).to_have_value("192.168.1.10")
    gateway_ip.fill("192.168.1.25")
    page.get_by_role("button", name="Save Config").click()

    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
    assert saved_payload["devices"]["gateway"]["ip_address"] == "192.168.1.25"
    assert saved_payload["devices"]["gateway"]["transport_mode"] == "tunnel"
    assert saved_payload["devices"]["future_device"] == {"hardware_name": ["Future Device"]}
