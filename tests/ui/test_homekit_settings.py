"""Browser tests for the HomeKit settings fieldset (issue #89)."""

import json
import os
import re
from pathlib import Path

import pytest
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


@pytest.mark.skipif(os.name == "nt", reason="the isolated real app requires POSIX host modules")
@pytest.mark.parametrize(
    ("mode", "override", "send_extents", "stop", "stop_same"),
    [
        ("default", None, True, False, False),
        ("enabled", True, False, True, False),
        ("disabled", False, False, False, True),
    ],
)
def test_real_homekit_save_reload_and_screenshot(
    page: Page, emulator_server, mode, override, send_extents, stop, stop_same
):
    """Exercise actual config GET/POST, disk persistence and a fresh page load."""
    config_path = emulator_server["generator_config"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key in (
        "homekit_enabled",
        "homekit_rollershutter_sendUpDownForExtents",
        "homekit_rollershutter_stop",
        "homekit_rollershutter_stopSameDirection",
    ):
        config["general"].pop(key, None)
    config["general"]["central_function_keyword"] = "acceptance-central"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    page.add_init_script("window.localStorage.setItem('knx_to_openhab.locale', 'de')")
    # Only the external release lookup is stubbed. Config routes remain real.
    page.route(
        "**/api/version/check",
        lambda route: route.fulfill(
            content_type="application/json", body='{"update_available": false}'
        ),
    )
    page.set_viewport_size({"width": 1440, "height": 1000})

    def open_loaded_settings():
        page.locator("#settings-section .card-header").click()
        expect(page.locator("#conf-central-keyword")).to_have_value("acceptance-central")

    page.goto(emulator_server["base_url"])
    open_loaded_settings()
    expect(page.locator("#conf-homekit-mode-default")).to_be_checked()
    expect(page.locator("#conf-homekit-send-up-down")).to_be_checked()
    expect(page.locator("#conf-homekit-stop")).not_to_be_checked()
    expect(page.locator("#conf-homekit-stop-same-direction")).not_to_be_checked()

    page.locator(f"#conf-homekit-mode-{mode}").check()
    page.locator("#conf-homekit-send-up-down").set_checked(send_extents)
    page.locator("#conf-homekit-stop").set_checked(stop)
    page.locator("#conf-homekit-stop-same-direction").set_checked(stop_same)
    with page.expect_response(
        lambda response: response.url.endswith("/api/config") and response.request.method == "POST"
    ) as saved:
        page.locator("#settings-section button[onclick='saveConfig(false)']").click()
    assert saved.value.ok
    expect(page.locator("#configStatus")).to_have_class("status-message success")

    expected = {
        "homekit_rollershutter_sendUpDownForExtents": send_extents,
        "homekit_rollershutter_stop": stop,
        "homekit_rollershutter_stopSameDirection": stop_same,
        "central_function_keyword": "acceptance-central",
    }
    persisted = json.loads(config_path.read_text(encoding="utf-8"))["general"]
    loaded = page.request.get(f"{emulator_server['base_url']}/api/config")
    assert loaded.ok
    fetched = loaded.json()["general"]
    for key, value in expected.items():
        assert persisted[key] == value
        assert fetched[key] == value
    for general in (persisted, fetched):
        if override is None:
            assert "homekit_enabled" not in general
        else:
            assert general["homekit_enabled"] is override

    page.reload()
    open_loaded_settings()
    expect(page.locator(f"#conf-homekit-mode-{mode}")).to_be_checked()
    expect(page.locator("#conf-homekit-send-up-down")).to_be_checked(checked=send_extents)
    expect(page.locator("#conf-homekit-stop")).to_be_checked(checked=stop)
    expect(page.locator("#conf-homekit-stop-same-direction")).to_be_checked(checked=stop_same)
    screenshot_dir = Path("test-results/homekit")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    page.locator("fieldset:has(#conf-homekit-mode-default)").screenshot(
        path=str(screenshot_dir / f"issue89-{mode}-saved-reloaded.png")
    )
    (screenshot_dir / f"issue89-{mode}-roundtrip.json").write_text(
        json.dumps({"mode": mode, "override": override, "verified": expected}, indent=2),
        encoding="utf-8",
    )
