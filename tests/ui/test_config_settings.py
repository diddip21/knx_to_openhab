import json
import pytest
from playwright.sync_api import Page, expect
import os

# Use the base_url from conftest.py if available, otherwise fallback
BASE_URL = "http://127.0.0.1:8081"

def get_config():
    config_path = os.path.join(os.getcwd(), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@pytest.fixture
def test_page(page: Page):
    """Provide a page session, handling login if necessary."""
    page.goto(BASE_URL)
    
    # Check if login is required (only if auth is enabled in test server)
    if "login" in page.url.lower() or page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "logihome")
        page.click("button[type='submit']")
        page.wait_for_load_state("networkidle")
    
    return page

def test_config_ui_consistency(test_page: Page):
    """Verify that Web UI configuration settings match config.json."""
    page = test_page
    config = get_config()
    
    # 1. Check if settings section is collapsed by default
    settings_content = page.locator("#settings-content")
    # In the UI, it's set to display: none;
    expect(settings_content).not_to_be_visible()
    
    # 2. Expand settings section
    # Use a more specific locator for the header
    page.click(".card-header:has-text('Configuration Settings')")
    expect(settings_content).to_be_visible()
    
    # 3. Verify General settings
    # Items Path
    expect(page.locator("#conf-items-path")).to_have_value(config.get('items_path', ''))
    # Things Path
    expect(page.locator("#conf-things-path")).to_have_value(config.get('things_path', ''))
    # Sitemaps Path
    expect(page.locator("#conf-sitemaps-path")).to_have_value(config.get('sitemaps_path', ''))
    # InfluxDB Path
    expect(page.locator("#conf-influx-path")).to_have_value(config.get('influx_path', ''))
    # Fenster Rules Path
    expect(page.locator("#conf-fenster-path")).to_have_value(config.get('fenster_path', ''))
    # Transform Path
    expect(page.locator("#conf-transform-path")).to_have_value(config.get('transform_dir_path', ''))
    
    # Naming Conventions
    gen = config.get('general', {})
    if gen.get('FloorNameAsItIs'):
        expect(page.locator("#conf-floor-asis")).to_be_checked()
    else:
        expect(page.locator("#conf-floor-asis")).not_to_be_checked()
        
    if gen.get('FloorNameFromDescription'):
        expect(page.locator("#conf-floor-desc")).to_be_checked()
    else:
        expect(page.locator("#conf-floor-desc")).not_to_be_checked()
        
    expect(page.locator("#conf-unknown-floor")).to_have_value(gen.get('unknown_floorname', 'unknown'))
    expect(page.locator("#conf-unknown-room")).to_have_value(gen.get('unknown_roomname', 'unknown'))
    
    # Prefix settings
    expect(page.locator("#conf-floor-prefix")).to_have_value(gen.get('item_Floor_nameshort_prefix', '='))
    expect(page.locator("#conf-room-prefix")).to_have_value(gen.get('item_Room_nameshort_prefix', '+'))

    # Verify that ETS Export Path is NOT present
    expect(page.locator("text=ETS Export Path")).to_have_count(0)
    expect(page.locator("#conf-ets-export")).to_have_count(0)

if __name__ == "__main__":
    pytest.main([__file__])
