"""UI tests for the HomeKit settings in the General tab (issue #89).

Covers the tri-state HomeKit mode, the rollershutter end-position default
(``sendUpDownForExtents``) and the independent optional stop parameters:
defaults display correctly, an explicit ``false`` survives saving, and
neighbouring ``general`` keys are never discarded.
"""

import json

import pytest
from playwright.sync_api import Page, expect

HOMEKIT_FIELDSET = "fieldset:has(legend:has-text('HomeKit'))"


def _config(homekit_enabled=None, extents=None, stop=None, stop_same=None):
    config = {
        "output_format": "legacy",
        "items_path": "openhab/items/knx.items",
        "things_path": "openhab/things/knx.things",
        "sitemaps_path": "openhab/sitemaps/knx.sitemap",
        "influx_path": "openhab/persistence/influxdb.persist",
        "fenster_path": "openhab/rules/fenster.rules",
        "yaml_path": "openhab/yaml/knx.yaml",
        "general": {
            "FloorNameAsItIs": False,
            "FloorNameFromDescription": False,
            "RoomNameAsItIs": False,
            "RoomNameFromDescription": True,
            "addMissingItems": False,
            "auto_place_unknown": False,
            "unknown_floorname": "unknown",
            "unknown_roomname": "unknown",
            "central_function_keyword": "zentral",
            "central_function_group": "Base",
            "notification_sensor_keyword": "Melden/Sensor",
        },
    }
    if homekit_enabled is not None:
        config["general"]["homekit_enabled"] = homekit_enabled
    if extents is not None:
        config["general"]["homekit_rollershutter_sendUpDownForExtents"] = extents
    if stop is not None:
        config["general"]["homekit_rollershutter_stop"] = stop
    if stop_same is not None:
        config["general"]["homekit_rollershutter_stopSameDirection"] = stop_same
    return config


def _route_config(page: Page, config, saved_payload):
    def config_route(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(config),
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


def _open_general_settings(page: Page, base_url: str) -> None:
    page.goto(base_url)
    if page.locator("input[name='username']").count() > 0:
        pytest.skip("Set UI_AUTH_USER and UI_AUTH_PASSWORD to test authenticated UI")
    page.get_by_role("combobox", name="Sprache / Language").select_option("en")
    settings_section = page.locator("#settings-section")
    expect(settings_section).to_be_visible()
    settings_content = page.locator("#settings-content")
    if not settings_content.is_visible():
        settings_section.locator(".card-header").click()
    expect(settings_content).to_be_visible()
    items_input = page.locator("#conf-items-path")
    expect(items_input).to_be_visible()
    expect(items_input).to_have_value("openhab/items/knx.items", timeout=10000)
    page.get_by_role("button", name="General").click()


def _mode_radio(page: Page, value: str):
    return page.locator(f'input[name="conf-homekit-mode"][value="{value}"]')


@pytest.mark.ui
class TestHomeKitSettingsDefaults:
    def test_missing_keys_show_ets_default_and_extents_on(
        self, page: Page, flask_server
    ):
        _route_config(page, _config(), {})
        _open_general_settings(page, flask_server)

        expect(_mode_radio(page, "default")).to_be_checked()
        expect(_mode_radio(page, "on")).not_to_be_checked()
        expect(_mode_radio(page, "off")).not_to_be_checked()
        # sendUpDownForExtents defaults to on when the key is missing.
        expect(page.locator("#conf-homekit-extents")).to_be_checked()
        expect(page.locator("#conf-homekit-stop")).not_to_be_checked()
        expect(page.locator("#conf-homekit-stopsamedirection")).not_to_be_checked()

    def test_explicit_false_and_off_mode_are_displayed(self, page: Page, flask_server):
        _route_config(page, _config(homekit_enabled=False, extents=False, stop=True), {})
        _open_general_settings(page, flask_server)

        expect(_mode_radio(page, "off")).to_be_checked()
        expect(page.locator("#conf-homekit-extents")).not_to_be_checked()
        expect(page.locator("#conf-homekit-stop")).to_be_checked()
        expect(page.locator("#conf-homekit-stopsamedirection")).not_to_be_checked()


@pytest.mark.ui
class TestHomeKitSettingsSave:
    def _save(self, page: Page, flask_server, config, saved_payload):
        _route_config(page, config, saved_payload)
        _open_general_settings(page, flask_server)

    def test_save_keeps_explicit_false_and_neighbor_keys(self, page: Page, flask_server):
        saved_payload = {}
        self._save(
            page,
            flask_server,
            _config(homekit_enabled=False, extents=False),
            saved_payload,
        )

        page.get_by_role("button", name="Save Config").click()
        expect(page.locator("#configStatus")).to_contain_text("Configuration saved")

        general = saved_payload["general"]
        # An explicit false is persisted, not reset to the true default.
        assert general["homekit_enabled"] is False
        assert general["homekit_rollershutter_sendUpDownForExtents"] is False
        # Untouched options keep their off default without being activated.
        assert general["homekit_rollershutter_stop"] is False
        assert general["homekit_rollershutter_stopSameDirection"] is False
        # Neighbouring general keys are never discarded by the save.
        assert general["FloorNameAsItIs"] is False
        assert general["FloorNameFromDescription"] is False
        assert general["addMissingItems"] is False
        assert general["auto_place_unknown"] is False
        assert general["unknown_floorname"] == "unknown"
        assert general["central_function_keyword"] == "zentral"
        assert general["item_Floor_nameshort_prefix"] == "="
        assert general["item_Room_nameshort_prefix"] == "+"

    def test_mode_off_and_stop_options_reach_the_saved_config(
        self, page: Page, flask_server
    ):
        saved_payload = {}
        self._save(page, flask_server, _config(), saved_payload)

        _mode_radio(page, "off").check()
        page.locator("#conf-homekit-stop").check()
        page.locator("#conf-homekit-stopsamedirection").check()
        page.get_by_role("button", name="Save Config").click()
        expect(page.locator("#configStatus")).to_contain_text("Configuration saved")

        general = saved_payload["general"]
        assert general["homekit_enabled"] is False
        assert general["homekit_rollershutter_sendUpDownForExtents"] is True
        assert general["homekit_rollershutter_stop"] is True
        assert general["homekit_rollershutter_stopSameDirection"] is True

    def test_default_mode_removes_the_override_key(self, page: Page, flask_server):
        saved_payload = {}
        self._save(page, flask_server, _config(homekit_enabled=True), saved_payload)

        expect(_mode_radio(page, "on")).to_be_checked()
        _mode_radio(page, "default").check()
        page.get_by_role("button", name="Save Config").click()
        expect(page.locator("#configStatus")).to_contain_text("Configuration saved")

        general = saved_payload["general"]
        # Back to "Default" means: no override key, the ETS comment decides.
        assert "homekit_enabled" not in general
