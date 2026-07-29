"""UI tests for project preview (building structure tree)."""

import json
import os
import re

import pytest
from playwright.sync_api import Page, expect

TEST_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "Charne.knxproj")
)

PREVIEW_PAYLOAD = {
    "metadata": {
        "project_name": "Test House",
        "gateway_ip": "192.168.1.100",
        "total_addresses": 5,
        "homekit_enabled": True,
        "alexa_enabled": False,
        "unknown_items": [
            {"name": "Unknown Light", "address": "1/2/99", "floor": "None", "room": "None"}
        ],
    },
    "buildings": [
        {
            "name": "Main Building",
            "description": "Hauptgebaeude",
            "floors": [
                {
                    "name": "Ground Floor",
                    "description": "Erdgeschoss",
                    "rooms": [
                        {
                            "name": "Living Room",
                            "description": "",
                            "address_count": 2,
                            "device_count": 1,
                            "addresses": [
                                {"Group name": "Light Ceiling", "Address": "1/2/3"},
                                {"Group name": "Blind Main", "Address": "1/2/4"},
                            ],
                        },
                        {
                            "name": "Kitchen",
                            "description": "",
                            "address_count": 1,
                            "device_count": 1,
                            "addresses": [
                                {"Group name": "Light Kitchen", "Address": "1/3/1"},
                            ],
                        },
                    ],
                },
                {
                    "name": "Upper Floor",
                    "description": "Obergeschoss",
                    "rooms": [
                        {
                            "name": "Bedroom",
                            "description": "",
                            "address_count": 1,
                            "device_count": 1,
                            "addresses": [
                                {"Group name": "Light Bedroom", "Address": "2/1/1"},
                            ],
                        }
                    ],
                },
            ],
        }
    ],
}

EMPTY_PREVIEW_PAYLOAD = {
    "metadata": {
        "project_name": None,
        "gateway_ip": None,
        "total_addresses": 0,
        "homekit_enabled": False,
        "alexa_enabled": False,
        "unknown_items": [],
    },
    "buildings": [],
}


def _setup_preview_routes(page: Page):
    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/project/preview") and method == "POST":
            return _fulfill(route, PREVIEW_PAYLOAD)
        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


def _setup_empty_preview_routes(page: Page):
    def _fulfill(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def handler(route, request):
        url = request.url
        method = request.method

        if url.endswith("/api/project/preview") and method == "POST":
            return _fulfill(route, EMPTY_PREVIEW_PAYLOAD)
        if url.endswith("/api/jobs"):
            return _fulfill(route, [])
        if url.endswith("/api/services"):
            return _fulfill(route, [])
        if url.endswith("/api/version/check"):
            return _fulfill(route, {"update_available": False})
        if url.endswith("/api/version"):
            return _fulfill(route, {"commit_short": "abc123"})
        if url.endswith("/api/config"):
            return _fulfill(route, {})
        if url.endswith("/api/status"):
            return _fulfill(route, {"status": "ok"})

        return _fulfill(route, {"error": f"unmocked {url}"}, status=404)

    page.route("**/api/**", handler)


@pytest.mark.ui
class TestProjectPreview:
    def _click_preview(self, page: Page, base_url, routes_fn=_setup_preview_routes):
        routes_fn(page)
        page.goto(base_url)
        if os.path.exists(TEST_FILE_PATH):
            page.locator("#fileInput").set_input_files(TEST_FILE_PATH)
        else:
            page.locator("#fileInput").set_input_files(
                {"name": "test.knxproj", "mimeType": "application/octet-stream", "buffer": b"\x00"}
            )
        page.locator("button:has-text('Preview Structure')").click()

    def test_preview_button_opens_structure(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)

        expect(page.locator("#status")).to_contain_text(
            re.compile(r"Project structure loaded|Structure loaded"), timeout=20000
        )
        expect(page.locator("#preview-section")).to_be_visible(timeout=10000)

    def test_preview_shows_metadata_cards(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        metadata = page.locator(".metadata-cards")
        expect(metadata).to_be_visible()
        expect(metadata).to_contain_text("Test House")
        expect(metadata).to_contain_text("192.168.1.100")

    def test_preview_tree_renders_buildings(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        expect(page.locator(".building-node")).to_have_count(1)
        expect(page.locator(".building-node")).to_contain_text("Main Building")

    def test_preview_tree_expand_floors(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        expect(page.locator(".floor-node")).to_have_count(2)
        expect(page.locator(".floor-node").first).to_contain_text("Ground Floor")
        expect(page.locator(".floor-node").last).to_contain_text("Upper Floor")

    def test_preview_tree_shows_rooms(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        expect(page.locator(".room-node")).to_have_count(3)
        room_texts = page.locator(".room-node").all_text_contents()
        assert any("Living Room" in t for t in room_texts)
        assert any("Kitchen" in t for t in room_texts)
        assert any("Bedroom" in t for t in room_texts)

    def test_preview_shows_unknown_items_banner(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        expect(page.locator(".metadata-card.unknown-items")).to_be_visible()
        expect(page.locator(".metadata-card.unknown-items")).to_contain_text("Unknown")

    def test_preview_empty_project(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url, _setup_empty_preview_routes)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        expect(page.locator(".building-node")).to_have_count(0)

    def test_preview_homekit_alexa_indicators(self, page: Page, base_url, flask_server):
        self._click_preview(page, base_url)
        expect(page.locator("#preview-section")).to_be_visible(timeout=20000)

        metadata = page.locator(".metadata-cards")
        expect(metadata).to_contain_text(re.compile(r"HomeKit|homekit", re.IGNORECASE))
