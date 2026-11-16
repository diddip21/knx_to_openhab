"""Browser tests for the HomeKit settings fieldset (issue #89)."""

import json
import re

from playwright.sync_api import Page, expect


def _base_config():
    return {
        "output_format": "legacy",
        "yaml_path": "openhab/yaml/knx.yaml",
        "items_path": "openhab/items/knx.items",
        "things_path": "openhab/things/knx.things",
        "sitemaps_path": "openhab/sitemaps/knx.sitemap",
        "influx_path": "openhab/persistence/influxdb.persist",
        "fenster_path": "openhab/rules/fenster.rules",
        "datapoint_mappings": {},
        "defines": {"dimmer": {"drop": []}, "switch": {"drop": []}},
        "regexpattern": {},
        "general": {
            "FloorNameAsItIs": True,
            "FloorNameFromDescription": False,
            "RoomNameAsItIs": False,
            "RoomNameFromDescription": False,
            "addMissingItems": True,
            "auto_place_unknown": True,
            "unknown_floorname": "unknown",
            "unknown_roomname": "unknown",
            "central_function_keyword": "zentral",
            "central_function_group": "Base",
            "notification_sensor_keyword": "Melden/Sensor",
            "item_Floor_nameshort_prefix": "=",
            "item_Room_nameshort_prefix": "+",
        },
        "devices": {"gateway": {"hardware_name": [], "ip_address": ""}},
    }


def _setup_routes(page: Page):
    page.add_init_script("window.localStorage.setItem('knx_to_openhab.locale', 'en')")
    config = _base_config()
    saved_requests = []

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/config") and method == "GET":
            return _fulfill(route, config)
        if url.endswith("/api/config") and method == "POST":
            saved_requests.append(json.loads(request.post_data or "{}"))
            return _fulfill(route, {"message": "Configuration updated successfully"})
        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})
        if url.endswith("/api/gateway/state"):
            return _fulfill(
                route,
                {
                    "configured_path": "",
                    "gateway_ip": "",
                    "gateway_mode": "",
                    "saved_override": "",
                    "managed_path": "",
                    "things_format": "dsl",
                    "reset_available": False,
                    "undo_available": False,
                    "runtime_status": "not_checked",
                },
            )
        if re.search(r"/api/job/[^/]+/events$", url):
            route.fulfill(status=200, content_type="text/event-stream", body="")
            return
        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)
    return config, saved_requests


def _expand_settings(page: Page):
    page.locator(".card-header:has-text('Configuration Settings')").click()
    # loadConfig() is scheduled one second after initialization. Wait for actual
    # configured data before editing/saving, not for an arbitrary 300 ms delay.
    expect(page.locator("#conf-central-keyword")).to_have_value("zentral", timeout=10000)


def test_homekit_defaults_are_shown_when_keys_are_missing(page: Page, base_url, flask_server):
    _setup_routes(page)
    page.goto(base_url)
    _expand_settings(page)

    expect(page.locator("#conf-homekit-mode-default")).to_be_checked()
    expect(page.locator("#conf-homekit-send-up-down")).to_be_checked()
    expect(page.locator("#conf-homekit-stop")).not_to_be_checked()
    expect(page.locator("#conf-homekit-stop-same-direction")).not_to_be_checked()


def test_explicit_homekit_values_are_loaded_without_losing_false(
    page: Page, base_url, flask_server
):
    config, _saved = _setup_routes(page)
    config["general"].update(
        {
            "homekit_enabled": False,
            "homekit_rollershutter_sendUpDownForExtents": False,
            "homekit_rollershutter_stop": True,
            "homekit_rollershutter_stopSameDirection": True,
        }
    )
    page.goto(base_url)
    _expand_settings(page)

    expect(page.locator("#conf-homekit-mode-disabled")).to_be_checked()
    expect(page.locator("#conf-homekit-send-up-down")).not_to_be_checked()
    expect(page.locator("#conf-homekit-stop")).to_be_checked()
    expect(page.locator("#conf-homekit-stop-same-direction")).to_be_checked()


def test_save_keeps_explicit_false_and_sibling_settings(page: Page, base_url, flask_server):
    _config, saved_requests = _setup_routes(page)
    page.goto(base_url)
    _expand_settings(page)

    page.locator("#conf-homekit-mode-enabled").check()
    page.locator("#conf-homekit-send-up-down").uncheck()
    page.locator("#conf-homekit-stop").check()
    page.locator("#conf-homekit-stop-same-direction").uncheck()
    page.locator("button:has-text('Save Config')").click()
    expect(page.locator("#configStatus")).to_contain_text("saved", timeout=10000)

    assert saved_requests
    general = saved_requests[-1]["general"]
    assert general["homekit_enabled"] is True
    assert general["homekit_rollershutter_sendUpDownForExtents"] is False
    assert general["homekit_rollershutter_stop"] is True
    assert general["homekit_rollershutter_stopSameDirection"] is False
    assert general["central_function_keyword"] == "zentral"
    assert general["FloorNameAsItIs"] is True


def test_save_default_mode_removes_the_override_key(page: Page, base_url, flask_server):
    _config, saved_requests = _setup_routes(page)
    page.goto(base_url)
    _expand_settings(page)

    page.locator("#conf-homekit-mode-default").check()
    page.locator("#conf-homekit-send-up-down").check()
    page.locator("button:has-text('Save Config')").click()
    expect(page.locator("#configStatus")).to_contain_text("saved", timeout=10000)

    assert saved_requests
    general = saved_requests[-1]["general"]
    assert "homekit_enabled" not in general
    assert general["homekit_rollershutter_sendUpDownForExtents"] is True
    assert general["homekit_rollershutter_stop"] is False
    assert general["homekit_rollershutter_stopSameDirection"] is False
