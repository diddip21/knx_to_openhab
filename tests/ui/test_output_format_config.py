"""UI coverage for the legacy/YAML output format settings."""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.ui
def test_output_format_shows_only_its_model_paths(page: Page, base_url, flask_server):
    page.goto(base_url)

    settings_content = page.locator("#settings-content")
    if not settings_content.is_visible():
        page.locator("#settings-section .card-header").click()
    expect(settings_content).to_be_visible()
    expect(page.locator("#conf-yaml-path")).to_have_value("openhab/yaml/knx.yaml", timeout=10000)

    output_format = page.locator("#conf-output-format")
    yaml_paths = page.locator("#yaml-path-group")
    legacy_paths = page.locator("#legacy-model-paths")
    original_format = output_format.input_value()
    legacy_path_values = {
        path_id: page.locator(f"#{path_id}").input_value()
        for path_id in ("conf-items-path", "conf-things-path", "conf-sitemaps-path")
    }

    output_format.select_option("yaml")
    expect(yaml_paths).to_be_visible()
    expect(legacy_paths).to_be_hidden()
    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
    page.get_by_role("button", name="Reload Config").click()
    expect(output_format).to_have_value("yaml")
    expect(yaml_paths).to_be_visible()
    expect(legacy_paths).to_be_hidden()
    for path_id, path_value in legacy_path_values.items():
        expect(page.locator(f"#{path_id}")).to_have_value(path_value)

    output_format.select_option(original_format)
    expect(yaml_paths).to_be_hidden()
    expect(legacy_paths).to_be_visible()
    page.get_by_role("button", name="Save Config").click()
    expect(page.locator("#configStatus")).to_contain_text("Configuration saved")
