"""Browser regression tests for the HomeKit settings in the General tab."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

KEY_EXTENTS = "homekit_rollershutter_sendUpDownForExtents"
KEY_STOP = "homekit_rollershutter_stop"
KEY_STOP_SAME_DIRECTION = "homekit_rollershutter_stopSameDirection"


def _open_general_settings(page: Page, base_url: str) -> None:
    page.goto(base_url)
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
    # The initial configuration load is scheduled shortly after page startup.
    # Wait for it before editing so it cannot overwrite the first save result.
    expect(page.locator("#configStatus")).to_contain_text("Configuration loaded", timeout=10000)
    settings_section = page.locator("#settings-section")
    expect(settings_section).to_be_visible()
    settings_content = page.locator("#settings-content")
    if not settings_content.is_visible():
        settings_section.locator(".card-header").click()
    expect(settings_content).to_be_visible()
    page.get_by_role("button", name="General").click()
    expect(page.locator("#conf-homekit-extents")).to_be_visible(timeout=10000)


def _save_and_reload(page: Page) -> None:
    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
    page.get_by_role("button", name="Reload Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration loaded")


def _saved_general(ui_server_environment) -> dict:
    config = json.loads(ui_server_environment["generator_config_file"].read_text(encoding="utf-8"))
    return config["general"]


def _maybe_capture_screenshot(page: Page) -> None:
    if os.getenv("SAVE_UI_SCREENSHOTS") == "1":
        screenshot_dir = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.locator("#tab-general").screenshot(path=str(screenshot_dir / "homekit-settings.png"))


@pytest.mark.ui
def test_homekit_defaults_and_optional_stops_round_trip(
    page: Page, flask_server, ui_server_environment
):
    _open_general_settings(page, flask_server)

    expect(page.locator('input[name="conf-homekit-mode"][value="ets"]')).to_be_checked()
    expect(page.locator("#conf-homekit-extents")).to_be_checked()
    expect(page.locator("#conf-homekit-stop")).not_to_be_checked()
    expect(page.locator("#conf-homekit-stop-same")).not_to_be_checked()

    page.locator("#conf-homekit-extents").uncheck()
    page.locator("#conf-homekit-stop").check()
    page.locator("#conf-homekit-stop-same").check()
    _save_and_reload(page)

    expect(page.locator('input[name="conf-homekit-mode"][value="ets"]')).to_be_checked()
    expect(page.locator("#conf-homekit-extents")).not_to_be_checked()
    expect(page.locator("#conf-homekit-stop")).to_be_checked()
    expect(page.locator("#conf-homekit-stop-same")).to_be_checked()

    general = _saved_general(ui_server_environment)
    assert general[KEY_EXTENTS] is False
    assert general[KEY_STOP] is True
    assert general[KEY_STOP_SAME_DIRECTION] is True
    assert general["central_function_keyword"] == "zentral"
    _maybe_capture_screenshot(page)


@pytest.mark.ui
def test_homekit_mode_override_round_trip(page: Page, flask_server, ui_server_environment):
    _open_general_settings(page, flask_server)

    page.locator('input[name="conf-homekit-mode"][value="disabled"]').check()
    _save_and_reload(page)
    expect(page.locator('input[name="conf-homekit-mode"][value="disabled"]')).to_be_checked()
    assert _saved_general(ui_server_environment)["homekit_enabled"] is False

    page.locator('input[name="conf-homekit-mode"][value="enabled"]').check()
    _save_and_reload(page)
    expect(page.locator('input[name="conf-homekit-mode"][value="enabled"]')).to_be_checked()
    assert _saved_general(ui_server_environment)["homekit_enabled"] is True

    page.locator('input[name="conf-homekit-mode"][value="ets"]').check()
    _save_and_reload(page)
    expect(page.locator('input[name="conf-homekit-mode"][value="ets"]')).to_be_checked()
    general = _saved_general(ui_server_environment)
    assert "homekit_enabled" not in general
    assert general["central_function_keyword"] == "zentral"
