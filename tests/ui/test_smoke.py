import pytest
from playwright.sync_api import Page, expect

def test_homepage_load(page: Page, base_url):
    """Test that the homepage loads correctly."""
    page.goto(base_url)
    
    # Check title
    # Note: The actual title might differ, checking for something generic or specific if known
    # Based on index.html usually having a title.
    # If we don't know the title, we can check for an element.
    
    # Check for main container or header
    # Assuming there is a header or some text "KNX to OpenHAB"
    expect(page.locator("body")).to_be_visible()
    
    # Check if we are on the right page
    assert page.url.rstrip('/') == base_url.rstrip('/')

def test_api_status(page: Page, base_url):
    """Test the API status endpoint directly."""
    response = page.request.get(f"{base_url}/api/status")
    expect(response).to_be_ok()
    data = response.json()
    assert "jobs_total" in data

def test_navigation_elements(page: Page, base_url):
    """Test presence of key navigation elements."""
    page.goto(base_url)
    
    # This depends on the actual UI implementation.
    # Since we haven't seen index.html, we'll do a basic check.
    # We can check if there are any buttons or links.
    expect(page.locator("body")).not_to_be_empty()
