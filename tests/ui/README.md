# Web UI Tests

Playwright regression tests cover authentication, uploads, previews, job lifecycle,
settings, package updates, deployment and rollback flows.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements-dev.txt
   python -m playwright install chromium
   ```

2. Run tests:
   ```bash
   # Run all UI tests
   pytest tests/ui/ -v -m ui

   # Run specific test
   pytest tests/ui/test_ui_smoke.py::test_homepage_loads -v

   # Run with visible browser (headed mode)
   pytest tests/ui/ -v -m ui --headed

   # Run slow tests
   pytest tests/ui/ -v -m "ui and slow"
   ```

## Test Structure

- `conftest.py`: Fixtures for starting the Flask test server and configuring Playwright
- `test_ui_smoke.py`: Homepage, upload form, navigation and status endpoint smoke checks
- Other `test_*.py` files: Focused browser regression suites for each user flow

## Writing Tests

### Test Markers

- `@pytest.mark.ui`: All UI tests should have this marker
- `@pytest.mark.slow`: Tests that take longer than 5 seconds

### Fixtures Available

- `page`: Playwright Page object (provided by pytest-playwright)
- `flask_server`: Starts the Flask test server and provides its base URL
- `base_url`: Configured UI URL (defaults to `http://127.0.0.1:8085`)

### Example Test

```python
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.ui
def test_example(page: Page, flask_server):
    page.goto(flask_server)
    expect(page).to_have_title("KNX to openHAB")
```

## Troubleshooting

### Server doesn't start

- Check if port 8085 is already in use (or the port configured by `UI_BASE_URL`)
- Ensure Flask and all dependencies are installed
- Check logs in test output

### Tests timeout

- Increase timeout in conftest.py `max_retries`
- Check if server is actually starting (run manually: `python -m web_ui.backend`)

### Elements not found

- Run with `--headed` to see browser
- Use `page.screenshot(path="debug.png")` to capture state
- Check actual HTML structure matches selectors
