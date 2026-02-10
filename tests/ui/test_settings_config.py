"""UI tests for settings/config tabs and save actions."""

import re

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
