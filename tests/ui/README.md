# Web UI Playwright Tests

The browser suite in this directory exercises the Flask Web UI with pytest and
Playwright. It uses the `ui` marker and Chromium (configured in `pytest.ini`).
Most tests stub API responses so that browser assertions are deterministic and
do not deploy or modify a real OpenHAB installation.

## Setup and execution

From the repository root:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
playwright install chromium

# Full browser suite
pytest tests/ui/ -v -m ui

# Focused test or module
pytest tests/ui/test_ui_smoke.py::test_homepage_loads -v
pytest tests/ui/test_job_lifecycle_e2e.py -v

# Run with a visible browser
pytest tests/ui/ -v -m ui --headed

# Only tests explicitly marked slow
pytest tests/ui/ -v -m "ui and slow"
```

The default server URL is `http://127.0.0.1:8085`; set `UI_BASE_URL` to use a
different running instance. Set `UI_AUTH_USER` and `UI_AUTH_PASSWORD` when the
instance requires HTTP Basic authentication. Authentication/session behavior
also has isolated test-client coverage, and `auth_preview_server` starts a
temporary authenticated instance for screenshot tests.

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
- `test_sse_streaming.py`: event-stream delivery, status updates and log
  filtering.
- `test_settings_config.py`, `test_settings_advanced.py`,
  `test_output_format_config.py`: configuration tabs, advanced controls and
  legacy/YAML output settings.
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
- For auth-specific UI, use the isolated authenticated preview fixture rather
  than changing the shared unauthenticated test server.
- Store intentional screenshot evidence under `test-results/` so CI can upload
  it; do not write generated artifacts into source or fixture directories.

## Troubleshooting

- Install Chromium with `playwright install chromium` (or `playwright install
  --with-deps` on the Ubuntu CI runner).
- The default server uses port 8085; stop any process already listening there or
  choose another `UI_BASE_URL`.
- Run a failing test with `--headed` and inspect its pytest/Playwright output.
- On failure, pytest retains screenshots, video and traces according to
  `pytest.ini`; CI also uploads the `test-results/` directory.
