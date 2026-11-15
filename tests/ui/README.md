# Web UI Playwright Tests

The browser suite in this directory exercises the Flask Web UI with pytest and
Playwright. It uses the `ui` marker and Chromium (configured in `pytest.ini`).
Most tests stub API responses so that browser assertions are deterministic. The
`test_application_emulator.py` journey starts an isolated Flask instance and
uses the real upload validator, ETS parser, generator, staging, preview, deploy,
rollback and job deletion. Its OpenHAB root, job data and backups live under a
temporary directory; browser routes emulate only host services, package-manager
operations and GitHub update metadata.

## Setup and execution

From the repository root:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium

# Full browser suite
pytest tests/ui/ -v -m ui

# Focused test or module
pytest tests/ui/test_ui_smoke.py::test_homepage_loads -v -m ui
pytest tests/ui/test_job_lifecycle_e2e.py -v -m ui
pytest tests/ui/test_application_emulator.py -v -m ui

# Run with a visible browser
pytest tests/ui/ -v -m ui --headed

# Only tests explicitly marked slow
pytest tests/ui/ -v -m "ui and slow"
```

The main fixture starts its own server at `http://127.0.0.1:8085` by default;
set `UI_BASE_URL` to use a different local port. Keep the selected port free.
Set `UI_AUTH_USER` and `UI_AUTH_PASSWORD` when testing HTTP Basic authentication.
Authentication/session behavior also has isolated test-client coverage, and
`auth_preview_server` starts a temporary authenticated instance for screenshot tests.

## Coverage map

- `test_smoke.py`, `test_ui_smoke.py`, `test_web_interface.py`: page load,
  navigation, status and general interface smoke coverage.
- `test_auth_session.py`, `test_auth_screenshots.py`: authenticated session
  behavior, access control and login/dashboard/session-expiry screenshots.
- `test_project_preview.py`, `test_preview_dialog.py`, `test_file_preview.py`:
  project structure, generated-file preview and diff dialog behavior.
- `test_job_actions.py`, `test_job_lifecycle_e2e.py`,
  `test_upload_job_happy_path.py`: upload, job state, deploy, rollback,
  reprocessing and deletion flows.
- `test_application_emulator.py`: real end-to-end generation and deployment
  against an isolated server, plus emulated service restart, package refresh
  and application-update discovery.
- `test_sse_streaming.py`: event-stream delivery, status updates and log
  filtering.
- `test_settings_config.py`, `test_settings_advanced.py`: configuration tabs,
  advanced controls, filters, mappings and definitions.
- `test_services_cloud.py`, `test_service_update_polling.py`,
  `test_update_system.py`: service/cloud controls, package polling and update
  behavior.
- `test_upload_flow.py`, `test_upload_security.py`: upload validation and
  security-related UI behavior.
- `conftest.py`: server, authentication, timeout and browser fixtures.

All tests in `tests/ui/` are marked `ui` during collection. The `slow` marker is
available for individually identified long-running cases; it is not applied to
the entire suite.

## Screenshots, video and traces

The authentication screenshot tests write test-only login, dashboard and
expired-session captures under `test-results/screenshots/`. GitHub Actions
uploads `test-results/` as the `ui-screenshots-and-reports` artifact for each UI
run, including screenshots and reports produced by the tests. Pytest is also
configured to retain screenshots, video and traces on failure. These captures
use temporary test configuration and synthetic data; they are evidence of the
test UI, not screenshots of a user's live OpenHAB instance.

## Adding a test

- Prefer visible, user-observable assertions (`expect(...)`) over implementation
  details.
- Mock external API behavior with `page.route(...)`; keep each test independent.
- Use the `page`, `base_url` and `flask_server` fixtures where appropriate.
- Use `emulator_server` for a full-stack browser journey. It redirects all
  generated files, job data and backups into `tmp_path`; keep OS service,
  package installation and self-update actions behind browser route stubs.
- For auth-specific UI, use the isolated authenticated preview fixture rather
  than changing the shared unauthenticated test server.
- Store intentional screenshot evidence under `test-results/` so CI can upload
  it; do not write generated artifacts into source or fixture directories.

## Troubleshooting

- Install Chromium with `playwright install chromium` (or `playwright install
  --with-deps` on the Ubuntu CI runner).
- The main fixture uses port 8085; stop any process already listening there or
  choose another `UI_BASE_URL`.
- Run a failing test with `--headed` and inspect its pytest/Playwright output.
- On failure, pytest retains screenshots, video and traces according to
  `pytest.ini`; CI also uploads the `test-results/` directory.
