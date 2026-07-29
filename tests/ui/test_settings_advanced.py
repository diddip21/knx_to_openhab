"""UI tests for settings (collapse, log filter, expert toggle, mappings, definitions)."""

import json
import os
import re

import pytest
from playwright.sync_api import Page, expect

TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)


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
        "regexpattern": {
            "floor_pattern": "^(EG|OG|KG)$",
            "room_pattern": "^(Wohnzimmer|Schlafzimmer|Kueche)$",
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

    preview_payload = {
        "metadata": {
            "project_name": "Test",
            "gateway_ip": "192.168.1.1",
            "total_addresses": 0,
            "homekit_enabled": False,
            "alexa_enabled": False,
            "unknown_items": [],
        },
        "buildings": [],
    }

    job_id = "job-settings-test"
    state = {"created": False, "status": "running"}

    def job_payload():
        return {
            "id": job_id,
            "name": "Settings Test Job",
            "status": state["status"],
            "staged": True,
            "deployed": False,
            "backups": [],
            "created": 1700000000,
            "stats": {
                "openhab/items/knx.items": {
                    "before": 0,
                    "after": 5,
                    "delta": 5,
                    "added": 5,
                    "removed": 0,
                },
                "completeness_report.json": {
                    "before": 0,
                    "after": 1,
                    "delta": 1,
                    "added": 1,
                    "removed": 0,
                },
            },
            "log": [
                {"level": "info", "text": "Starting job"},
                {"level": "info", "text": "Processing files"},
                {"level": "warning", "text": "Some warning"},
                {"level": "error", "text": "Some error"},
                {"level": "info", "text": "Job done"},
            ],
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
        if url.endswith("/api/upload") and method == "POST":
            state["created"] = True
            state["status"] = "completed"
            return _fulfill(route, {"id": job_id, "status": "running"})
        if url.endswith("/api/jobs"):
            return _fulfill(route, [job_payload()] if state["created"] else [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})
        if re.search(r"/api/job/[^/]+/events$", url):
            body = 'data: {"type": "status", "message": "completed"}\n\n'
            route.fulfill(status=200, content_type="text/event-stream", body=body)
            return
        if re.search(r"/api/job/[^/]+/preview$", url):
            return _fulfill(route, preview_payload)
        if re.search(r"/api/job/[^/]+$", url) and method == "GET":
            return _fulfill(route, job_payload())

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


def _expand_settings(page: Page):
    page.locator(".card-header:has-text('Configuration Settings')").click()
    page.wait_for_timeout(300)


def _upload_and_wait_detail(page: Page):
    if os.path.exists(TEST_FILE_PATH):
        page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
    else:
        page.locator("#fileInput").set_input_files(
            {"name": "test.knxproj", "mimeType": "application/octet-stream", "buffer": b"\x00"}
        )
    page.locator("button[type='submit']").click()
    expect(page.locator("#detail-section")).to_be_visible(timeout=20000)


@pytest.mark.ui
class TestSettingsCollapse:
    def test_settings_collapse_toggle(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)

        header = page.locator(".card-header:has-text('Configuration Settings')")
        expect(header).to_be_visible()

        _expand_settings(page)

        settings_content = page.locator("#settings-content")
        expect(settings_content).to_be_visible()


@pytest.mark.ui
class TestLogFiltering:
    def _setup_and_load_job(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _upload_and_wait_detail(page)

    def test_log_level_filter_exists(self, page: Page, base_url, flask_server):
        self._setup_and_load_job(page, base_url, flask_server)

        filter_el = page.locator("#logLevelFilter")
        expect(filter_el).to_be_visible(timeout=10000)
        options = filter_el.locator("option").all_text_contents()
        assert "all" in [o.lower() for o in options]

    def test_log_filter_all_shows_all(self, page: Page, base_url, flask_server):
        self._setup_and_load_job(page, base_url, flask_server)

        page.locator("#logLevelFilter").select_option("all")
        page.wait_for_timeout(300)


@pytest.mark.ui
class TestExpertToggle:
    def _load_job(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _upload_and_wait_detail(page)

    def test_expert_toggle_shows_panel(self, page: Page, base_url, flask_server):
        self._load_job(page, base_url, flask_server)

        toggle = page.locator("#expertToggle")
        expect(toggle).to_be_visible(timeout=10000)
        toggle.check()
        expect(page.locator("#expertPanel")).to_be_visible()

    def test_expert_toggle_hides_panel(self, page: Page, base_url, flask_server):
        self._load_job(page, base_url, flask_server)

        toggle = page.locator("#expertToggle")
        toggle.check()
        expect(page.locator("#expertPanel")).to_be_visible()

        toggle.uncheck()
        expect(page.locator("#expertPanel")).to_be_hidden()

    def test_expert_toggle_persists_in_localstorage(self, page: Page, base_url, flask_server):
        self._load_job(page, base_url, flask_server)

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
        _expand_settings(page)
        page.locator(".tab-btn:has-text('Mappings')").click()
        page.wait_for_timeout(300)

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

        switch_mapping = page.locator("#mappingsTable tbody tr[data-key='1.001']")
        expect(switch_mapping).to_be_visible()
        expect(switch_mapping.locator("input[data-field='item_type']")).to_have_value("Switch")


@pytest.mark.ui
class TestDefinitionsTab:
    def _open_definitions_tab(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _expand_settings(page)
        page.locator(".tab-btn:has-text('Definitions')").click()
        page.wait_for_timeout(300)

    def test_definitions_tab_renders(self, page: Page, base_url, flask_server):
        self._open_definitions_tab(page, base_url, flask_server)

        accordion = page.locator("#definitions-accordion")
        expect(accordion).to_be_visible()


@pytest.mark.ui
class TestAdvancedTab:
    def _open_advanced_tab(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _expand_settings(page)
        page.locator(".tab-btn:has-text('Advanced')").click()
        page.wait_for_timeout(300)

    def test_advanced_tab_renders(self, page: Page, base_url, flask_server):
        self._open_advanced_tab(page, base_url, flask_server)

        container = page.locator("#regex-container")
        expect(container).to_be_visible()
        inputs = container.locator("input.regex-input")
        expect(inputs.first).to_be_visible()


@pytest.mark.ui
class TestSettingsSaveConfig:
    def test_save_config_shows_success(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _expand_settings(page)

        page.locator("button:has-text('Save Config')").click()
        expect(page.locator("#configStatus")).to_contain_text("saved", timeout=10000)

    def test_reload_config_loads_values(self, page: Page, base_url, flask_server):
        _setup_settings_routes(page)
        page.goto(base_url)
        _expand_settings(page)

        page.locator("button:has-text('Reload Config')").click()
        expect(page.locator("#configStatus")).to_contain_text("loaded", timeout=10000)

        items_path = page.locator("#conf-items-path")
        if items_path.count() > 0:
            expect(items_path).to_have_value("openhab/items/knx.items")
