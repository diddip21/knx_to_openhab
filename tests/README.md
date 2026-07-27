# Testing Guide for knx_to_openhab

This repository contains automated tests to ensure the application works reliably across platforms (especially Raspberry Pi with DietPi).

## Test Structure

```
tests/
├── conftest.py              # Shared pytest fixtures
├── integration/             # Integration tests
│   ├── test_output_validation.py  # Golden file comparison
│   ├── test_business_logic.py     # Log/warning verification
│   ├── test_file_import.py        # JSON and .knxproj import
│   └── test_installer.py          # Installer script validation
├── ui/                      # UI tests with Playwright
│   ├── test_web_interface.py
│   ├── test_upload_flow.py
│   ├── test_job_actions.py
│   └── ...
├── fixtures/                # Test data
│   ├── Charne.knxproj       # KNX binary project file
│   ├── mini_project.json    # Minimal test project
│   └── expected_output/     # Golden files (Charne, Mini, UploadJson)
├── test_address_selection.py
├── test_auto_place_unknowns.py
├── test_core_functionality.py
├── test_ets_helpers.py
├── test_full_generation.py
├── test_output_config.py
├── test_things_completeness.py
├── test_web_ui_job_endpoints.py
└── README.md               # This file
```

## Prerequisites

### Base Installation
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### For UI Tests
```bash
playwright install chromium
```

## Running Tests

### Core Tests
```bash
pytest -q -m "not ui" --ignore=tests/ui
```

### Unit Tests Only
```bash
pytest tests/test_*.py -v
```

### Integration Tests Only
```bash
pytest tests/integration -v
```

### UI Tests (server must be running!)
```bash
# Terminal 1: Start server
flask --app web_ui.backend.app:app run --debug --port 8085

# Terminal 2: Run UI tests
pytest tests/ui/ -v -o addopts=
```

### Tests with Coverage
```bash
pytest --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

### Specific Tests
```bash
# Filter by name
pytest -k "test_login"

# By marker
pytest tests/test_*.py -v
pytest -m integration
pytest -m ui
```

## CI/CD Pipeline

Tests run automatically on every push via GitHub Actions:

- **Lint:** Black + isort + flake8
- **Core Tests:** Python 3.12 + 3.13 matrix on ubuntu-latest
- **UI Tests:** Playwright with Chromium (depends on core tests passing)

Status: [![CI Tests](https://github.com/diddip21/knx_to_openhab/workflows/CI%20Tests/badge.svg)](https://github.com/diddip21/knx_to_openhab/actions)

## Golden File Testing

Golden files are reference outputs for regression testing. Located in `tests/fixtures/expected_output/` with three projects: Charne, Mini, UploadJson.

### Regenerate Golden Files
```bash
python scripts/regenerate_golden.py
```

### How It Works
1. Each test loads a JSON project fixture
2. Runs the full generation pipeline
3. Compares output line-by-line against golden files using `difflib.unified_diff`
4. Fails on ANY difference

## Writing New Tests

### Unit Test Example
```python
# tests/test_example.py
import pytest

def test_example_function():
    """Test description."""
    result = your_function()
    assert result == expected_value
```

### Integration Test with Golden Files
```python
# tests/integration/test_output_validation.py
import pytest

GOLDEN_CASES = [
    ("Charne", "tests/Charne.knxproj.json", False),
    ("Mini", "tests/fixtures/mini_project.json", False),
]

@pytest.mark.parametrize("name,path,password", GOLDEN_CASES)
def test_output_matches_golden(name, path, password, temp_output_dir):
    # ... generate and compare
```

### UI Test Example
```python
# tests/ui/test_example.py
import pytest
from playwright.sync_api import Page

@pytest.mark.ui
def test_page_loads(page: Page):
    """Test that page loads correctly."""
    page.goto("http://localhost:8085")
    assert "KNX" in page.title()
```

## ARM Testing (Raspberry Pi Simulation)

### With Docker
```bash
docker buildx build --platform linux/arm64 -f Dockerfile.test -t knx-test:arm64 .
docker run --platform linux/arm64 knx-test:arm64
```

### On Real Raspberry Pi
```bash
ssh pi@raspberrypi.local
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab
pip install -r requirements.txt
pytest -v
```

## Troubleshooting

### Tests Can't Find Modules
```bash
# Ensure pytest.ini exists or set PYTHONPATH
export PYTHONPATH=.
pytest
```

### UI Tests Failing
```bash
# Check if server is running
curl http://localhost:8085

# Reinstall Playwright browser
playwright install --force chromium
```

### ARM Tests Not Working
```bash
# Install QEMU (Linux)
sudo apt-get install qemu-user-static

# Set up Docker Buildx
docker buildx create --use
```

## Best Practices

1. **Isolation**: Each test should be independent
2. **Use Fixtures**: Use `conftest.py` for shared setup logic
3. **Markers**: Use `@pytest.mark.ui`, `@pytest.mark.slow` etc.
4. **Docstrings**: Write descriptions for every test
5. **Coverage**: Aim for at least 80%

## Support

If you encounter issues:
1. Check [GitHub Actions Logs](https://github.com/diddip21/knx_to_openhab/actions)
2. Open an issue with test logs
3. Local debug output: `pytest -vv --tb=long`
