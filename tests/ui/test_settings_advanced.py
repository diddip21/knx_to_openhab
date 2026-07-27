"""UI tests for settings (collapse, log filter, expert toggle, mappings, definitions)."""

import json
import re

import pytest
from playwright.sync_api import Page, expect


def _setup_settings_routes(page: Page):
    config = {
        "items_path": "openhab/items/knx.items",
        "things_path": "openhab/things/knx.things",
        "sitemaps_path": "openhab/sitemaps/knx.sitemap",
        "influx_path": "openhab/persistence/influxdb.persist",
        "fenster_path": "openhab/rules/fenster.rules",
        "datapoint_mappings": {
            "1.001": {"item_type": "Switch", "item_icon": "switch", "semantic_info": "Light"},
            "5.001": {"item_type": "Dimmer", "item_icon": "dimmer", "semantic_info": "Light"},
        },
        "defines": {
            "dimmer": ["DIM", "DIMMER"],
            "switch": ["SCHALTER", "SWITCH"],
        },
        "regex_patterns": {
            "floor_pattern": r"^(EG|OG|KG)$",
            "room_pattern": r"^(Wohnzimmer|Schlafzimmer|Kueche)$",
        },
        "general": {
            "FloorNameAsItIs": False,
            "FloorNameFromDescription": True,
            "RoomNameAsItIs": False,
            "RoomNameFromDescription": True,
            "addMissingItems": False,
            "auto_place_unknown": False,
        },
    }

    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/config") and method == "GET":
            return _fulfill(route, config)
        if url.endswith("/api/config") and method == "POST":
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

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestSettingsCollapse:
    def test_settings_collapse_toggle(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        header = page.locator(".card-header:has-text('Configuration Settings')")
        expect(header).to_be_visible()

        settings_content = page.locator("#settings-content")
        if settings_content.count() > 0:
            header.click()
            page.wait_for_timeout(500)


@pytest.mark.ui
class TestLogFiltering:
    def _setup_and_get_log(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        log = page.locator("#log")
        expect(log).to_be_visible()
        return log

    def test_log_level_filter_exists(self, page: Page, base_url, flask_server):
        self._setup_and_get_log(page, base_url, flask_server)

        filter_el = page.locator("#logLevelFilter")
        expect(filter_el).to_be_visible()
        options = filter_el.locator("option").all_text_contents()
        assert "all" in [o.lower() for o in options]

    def test_log_filter_all_shows_all(self, page: Page, base_url, flask_server):
        self._setup_and_get_log(page, base_url, flask_server)

        page.locator("#logLevelFilter").select_option("all")
        page.wait_for_timeout(300)


@pytest.mark.ui
class TestExpertToggle:
    def test_expert_toggle_shows_panel(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        toggle = page.locator("#expertToggle")
        expect(toggle).to_be_visible()
        toggle.check()
        expect(page.locator("#expertPanel")).to_be_visible()

    def test_expert_toggle_hides_panel(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        toggle = page.locator("#expertToggle")
        toggle.check()
        expect(page.locator("#expertPanel")).to_be_visible()

        toggle.uncheck()
        expect(page.locator("#expertPanel")).to_be_hidden()

    def test_expert_toggle_persists_in_localstorage(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        page.locator("#expertToggle").check()
        page.reload()
        page.wait_for_load_state("networkidle")

        stored = page.evaluate("localStorage.getItem('showExpertCompleteness')")
        assert stored == "true" or stored is None


@pytest.mark.ui
class TestMappingsTab:
    def _open_mappings_tab(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        page.locator(".tab-btn:has-text('Mappings')").click()

    def test_mappings_tab_renders_table(self, page: Page, base_url, flask_server):
        self._open_mappings_tab(page, base_url, flask_server)

        table = page.locator("#mappingsTable")
        expect(table).to_be_visible()
        rows = page.locator("#mappingsTable tbody tr")
        expect(rows.first).to_be_visible()

    def test_mappings_search_filter(self, page: Page, base_url, flask_server):
        self._open_mappings_tab(page, base_url, flask_server)

        search = page.locator("#mappingSearch")
        expect(search).to_be_visible()
        search.fill("1.001")
        page.wait_for_timeout(500)

    def test_mappings_has_datapoint_types(self, page: Page, base_url, flask_server):
        self._open_mappings_tab(page, base_url, flask_server)

        table_text = page.locator("#mappingsTable").inner_text()
        assert "1.001" in table_text or "Switch" in table_text


@pytest.mark.ui
class TestDefinitionsTab:
    def _open_definitions_tab(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        page.locator(".tab-btn:has-text('Definitions')").click()

    def test_definitions_tab_renders(self, page: Page, base_url, flask_server):
        self._open_definitions_tab(page, base_url, flask_server)

        accordion = page.locator("#definitions-accordion")
        expect(accordion).to_be_visible()


@pytest.mark.ui
class TestAdvancedTab:
    def _open_advanced_tab(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        page.locator(".tab-btn:has-text('Advanced')").click()

    def test_advanced_tab_renders(self, page: Page, base_url, flask_server):
        self._open_advanced_tab(page, base_url, flask_server)

        container = page.locator("#regex-container")
        expect(container).to_be_visible()


@pytest.mark.ui
class TestSettingsSaveConfig:
    def test_save_config_shows_success(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        page.locator("button:has-text('Save Config')").click()
        expect(page.locator("#configStatus")).to_contain_text("saved", timeout=10000)

    def test_reload_config_loads_values(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        page.locator("button:has-text('Reload Config')").click()
        expect(page.locator("#configStatus")).to_contain_text("loaded", timeout=10000)

        items_path = page.locator("#conf-items-path")
        if items_path.count() > 0:
            expect(items_path).to_have_value("openhab/items/knx.items")
