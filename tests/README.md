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
│   └── expected_output/     # Golden files
│       ├── common/          # Shared outputs
│       ├── Charne/
│       ├── Mini/
│       └── UploadJson/
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

### All Tests
```bash
pytest
```

### Unit Tests Only
```bash
pytest -m unit -v
```

### Integration Tests Only
```bash
pytest tests/integration -v
```

### UI Tests (server must be running!)
```bash
# Terminal 1: Start server
flask --app web_ui.backend.app:app run --debug

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
pytest -m unit
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

Golden files are reference outputs for regression testing. Located in `tests/fixtures/expected_output/` with three projects: Charne, Mini, UploadJson. Identical persistence output is stored once in `common/influxdb.persist`; a project keeps its own file only when its output differs from that shared reference.

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


## Real openHAB 5.2 integration in Debian 13

[The openHAB integration workflow](../.github/workflows/openhab-real.yml)
boots a **disposable Debian 13 VM** with real systemd, Java 21, and the
official openHAB 5.2 APT packages (runtime plus matching add-ons). The
installed package is restricted to the latest available **5.2.x** version so
a later openHAB major/minor release cannot silently change the test target.

It first runs the existing real Debian installer smoke, then installs openHAB
and the KNX binding, reruns the KNX-to-openHAB setup against the actual
`/etc/openhab` installation, and generates a small **synthetic ETS Mini**
fixture using the project's real `gen_building()` and production output
templates. The test loads native YAML, then legacy Things/Items/Sitemap files
one at a time, and checks the actual openHAB REST collections for **all**
generated Items, KNX Things, custom channels, and Item-channel links. It also
checks the real services after restart. It does **not** count a running HTTP
server alone as proof that generated configuration was accepted.

Implementation:
- [`tests/smoke/openhab_real_smoke.sh`](smoke/openhab_real_smoke.sh):
  Debian+openHAB install and real integration lifecycle
- [`tests/smoke/generate_openhab_fixture.py`](smoke/generate_openhab_fixture.py):
  generate native YAML and legacy output from a synthetic ETS JSON fixture
- [`tests/smoke/verify_openhab_rest.py`](smoke/verify_openhab_rest.py):
  poll the actual openHAB API for Items, Things, channels and links

The workflow runs for relevant changes on integration branches and relevant
PRs targeting `main`. It also supports manual dispatch once the workflow
exists on the repository's default branch. On failures it archives
`test-results/openhab-real/` with package/Java versions, installation logs,
openHAB service logs, and any partial REST inspection reports.

**Limits:** The fictional gateway IP cannot connect to a real KNX bus;
an OFFLINE KNX bridge is expected. This validates registration and linking,
not bus telegram delivery or physical device behavior. It does not run the
DietPi image, physical hardware, a complete end-to-end update from a published
GitHub release, or actual KNX project files. This script contains deliberate
host modifications and must **never** be run outside disposable GitHub CI VMs.

## Debian VM systemd smoke test

The workflow at [`.github/workflows/debian-smoke.yml`](../.github/workflows/debian-smoke.yml)
boots disposable **Debian 12 and Debian 13** virtual machines using a pinned
QEMU-based Debian VM action and official Debian cloud images. Unlike the
mock-based setup tests, this exercises the real `systemctl`, Linux account and
group management, filesystem ownership, TCP listeners, `pip`/venv, and sudoers
policy.

The test script at [`tests/smoke/debian_smoke.sh`](smoke/debian_smoke.sh):

1. Verifies it is running as root in an isolated GitHub Actions Debian VM with
   real `systemd` as PID 1 (refuses to run on ordinary machines).
2. Stages the **checked-out commit**, not an unrelated published release, and
   seeds only synthetic Web UI credentials, an example upload, and a backup.
3. Checks that a foreign `knxohui.service` is rejected without being replaced.
4. Runs the actual `installer/setup.sh`, checks its started timer/service,
   authenticates to the Web UI, and verifies migration, password hashing,
   stored settings and backup contents.
5. Runs `install.sh --repair` and asserts preservation of the existing data.
6. Forces a real dependency-install failure **after services were stopped** and
   checks that the installer restores the previous service state.
7. Starts a competing TCP listener and checks that setup refuses the occupied
   Web UI port without losing data; then restarts the service via `systemctl`.

**Triggers:** updates to installer/smoke-relevant files on integration branches,
relevant PRs to `main`, and `workflow_dispatch` once the workflow is
available on the default branch. The action archives a seven-day diagnostic
artifact `debian-<release>-smoke-logs`.

**Limitations:** this does not install the complete openHAB Java runtime,
connect to a KNX gateway, reboot the VM, test DietPi-specific customizations,
or exercise release downloads / the online updater. The fixture upload and
backup are synthetic. Use a snapshot-backed DietPi/Raspberry Pi environment
for those final acceptance checks. Never run this smoke script on a live host.

## Real Web UI deploy -> openHAB 5.2 regression check

On the integration branch, [`.github/workflows/openhab-real.yml`](../.github/workflows/openhab-real.yml)
boots Debian 13 with a real openHAB 5.2 installation, Java 21 and KNX binding.
After its existing direct-file checks, the script
[`tests/smoke/web_deploy_e2e.py`](smoke/web_deploy_e2e.py) uses the
**live, authenticated Web UI HTTP endpoints**, rather than mocked responses:

1. Upload the public synthetic ETS Mini JSON fixture using `POST /api/upload`
   and wait for actual background generator completion.
2. Deploy staged legacy Items, Things and sitemap through
   `POST /api/job/<id>/deploy`; verify managed files, backup and REST objects.
3. Trigger `POST /api/job/<id>/rerun`, deploy the unchanged project again,
   and compare the actual deployed files for idempotency.
4. Change the generator setting through `POST /api/config`, upload/deploy as
   native YAML and verify that legacy output files are retired.
5. Call `POST /api/job/<id>/rollback`, verify legacy file restoration and
   reload via openHAB's REST API.

The [`openhab_log_guard.py`](smoke/openhab_log_guard.py) helper checks **only
new lines** in real `/var/log/openhab/openhab.log` and `events.log` following
each deployment. New ERROR/FATAL/exception lines and warnings about parser,
configuration or model loading fail the workflow. The single, exact
KNXnet/IP handshake timeout from the deliberately unreachable fixture gateway
`192.168.1.1:3671` is recorded separately as an expected test condition;
all other errors still fail. Captured REST responses,
log findings and step diagnostics are archived as artifacts for seven days.
An unconnected *synthetic* KNX gateway being OFFLINE is expected, not a reason
to fail the REST status assertion.

The same live upload and deploy endpoints are used by the Web UI's Deploy
button. This test covers the backend end-to-end; separate Playwright tests
cover the UI controls but currently mock the deployment response. It does not
guarantee correctness for arbitrary ETS files, real KNX hardware, HomeKit,
Alexa, all metadata combinations or future openHAB versions.

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
