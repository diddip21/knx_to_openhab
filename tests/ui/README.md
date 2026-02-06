# UI Tests

Automated browser tests using Playwright and pytest.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements-dev.txt
   playwright install
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

- `conftest.py`: Pytest fixtures for starting Flask server and configuring Playwright
- `test_ui_smoke.py`: Basic smoke tests to verify UI loads and critical elements exist
- Future: `test_ui_upload.py`, `test_ui_jobs.py`, etc.

## Writing Tests

### Test Markers

- `@pytest.mark.ui`: All UI tests should have this marker
- `@pytest.mark.slow`: Tests that take longer than 5 seconds

### Fixtures Available

- `page`: Playwright Page object (provided by pytest-playwright)
- `flask_server`: Base URL of running Flask server
- `base_url`: Same as flask_server (alternative name)

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

- Check if port 8080 is already in use
- Ensure Flask and all dependencies are installed
- Check logs in test output

### Tests timeout

- Increase timeout in conftest.py `max_retries`
- Check if server is actually starting (run manually: `python -m web_ui.backend.app`)

### Elements not found

- Run with `--headed` to see browser
- Use `page.screenshot(path="debug.png")` to capture state
- Check actual HTML structure matches selectors
