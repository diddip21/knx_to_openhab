# AGENTS.md — AI Agent Instructions for knx_to_openhab

## Project Summary

KNX to OpenHAB Generator parses ETS smart home project files (`.knxproj` / `.knxprojarchive`) and generates complete OpenHAB configuration: Things, Items, Sitemaps, Persistence rules, and Window-contact Rules. Two interfaces: a Flask Web UI (port 8085) and a CLI.

Target audience: German-speaking smart home users running OpenHAB on Raspberry Pi / DietPi.

## Data Flow

```
.knxproj file
  → xknxproject parser (KNXProject dict)
  → knxproject_to_openhab.py
      create_building()      → building/floor/room hierarchy
      get_addresses()        → flat list of group addresses with metadata
      put_addresses_in_building() → addresses placed into building tree
  → ets_to_openhab.py
      gen_building()         → generates legacy strings and a structured openHAB model
  → openhab_yaml.py
      validate_model()       → validates IDs and cross-references
      render_yaml()          → deterministic openHAB 5.2 YAML
      export_output()        → writes files using *.template wrappers
  → openhab/ output directory
      knx.items, knx.things, knx.sitemap, influxdb.persist
```

## Key Files

| File | Purpose |
|------|---------|
| `knxproject_to_openhab.py` | Entry point: parses `.knxproj`, builds building hierarchy, calls generator |
| `ets_to_openhab.py` | Core generator: `gen_building()` produces items/things/sitemap strings, `export_output()` writes files |
| `openhab_yaml.py` | Dependency-free openHAB 5.2 YAML renderer and semantic validator |
| `config.json` | Generator defaults: regex patterns, device detection rules, datapoint mappings, output paths |
| `config.py` | Loads `config.json`, normalizes values, detects OpenHAB paths. **Executes on import** — side effects at module level |
| `knxoh_paths.py` | Resolves installed and local-development configuration, data and backup paths |
| `utils.py` | Single helper: `get_datapoint_type()` |
| `ets_helpers.py` | Extracted helpers: `get_co_flags()`, `flags_match()`, `get_dpt_from_dco()` |
| `completeness.py` | Post-generation validation: checks Things for missing required channels |
| `*.template` | Output wrappers: `items.template`, `things.template`, `sitemap.template` — use `###items###` placeholders |
| `web_ui/backend/app.py` | Flask routes, session/CSRF checks, SSE and API endpoints |
| `web_ui/backend/auth.py` | Argon2id password verification and login rate limiting |
| `web_ui/backend/deploy_policy.py` | Validates and confines managed OpenHAB output paths |
| `web_ui/backend/jobs.py` | Job queue, staging/deploy, backup/rollback |
| `web_ui/backend/storage.py` | JSON persistence, atomic file writes |
| `web_ui/backend/updater.py` | Git-based self-update via GitHub API |
| `web_ui/backend/service_manager.py` | systemd service control |
| `web_ui/static/app.js` | Frontend SPA: vanilla JS, no framework |

## Coding Conventions

- **Python 3.12+** (target version in CI and pyproject.toml)
- **Black**: line-length 100, target py312
- **isort**: profile="black", line_length=100
- **flake8**: max-line-length 100, ignore E203/W503
- **mypy**: python_version 3.12, ignore missing imports
- Conventional commit messages: `feat:`, `fix:`, `chore:`, `style:`, `docs:`
- Item names use `i_` prefix + floor/room short names + shortened GA label
- `config.py` `special_char_map` handles umlaut replacement (ä→ae, ö→oe, etc.)

## Testing

### Run Tests

```bash
# Core tests (explicitly exclude browser tests)
pytest -q -m "not ui" --ignore=tests/ui

# Specific test groups
pytest tests/integration -v
pytest -m unit
pytest -m integration

# With coverage
pytest --cov=. --cov-report=html -m "not ui" --ignore=tests/ui

# UI tests (requires Playwright and Chromium; fixtures start the test server)
pytest tests/ui/ -v -m ui --tb=short
```

## Cross-Task Delivery Rules

- Keep issues actionable and reviewable: describe the user problem, intended behavior, scope, compatibility expectations, acceptance criteria, and relevant dependencies. Link active pull requests and state what remains outstanding; keep an issue open when a pull request covers only part of its scope.
- Start from the linked issue's acceptance criteria and trace the affected flow through the UI, API, configuration, and generated output. Keep existing defaults and configuration keys working unless the issue explicitly changes them.
- For a bug fix, add a regression test that fails on the previous behavior. For a feature, cover the normal path, the existing/default path, and invalid input where relevant. Run the focused tests first, then the full applicable suite.
- UI changes need committed screenshots of the finished interface in `docs/screenshots/`. Screenshots must show real app state, avoid secrets and personal data, and be referenced from the pull request with a short explanation of each view.
- Before calling work complete, run formatting/lint checks, core tests, relevant UI tests, and `git diff --check`. Report any checks that could not be run; do not state that a check passed without its output.
- A pull request should summarize user-visible behavior, compatibility/default behavior, tests and their results, and screenshots for UI changes. Keep scope focused and verify that saving one setting does not discard sibling configuration.
- When integrating several open PRs for combined testing, enumerate all open PRs first (including drafts), create a separate `developer/*` integration branch from the default branch, and merge source branches in dependency order. Do not modify the default branch during integration. Keep source PRs open unless closing them is explicitly requested; record the integrated PR list, conflicts and decisions in a GitHub-visible report.
- Combined product changes need a user-facing before/after guide linked from the README. Explain defaults, compatibility, setup or migration steps, and how to use each visible feature. Keep security, architecture and test details in the appropriate internal guides and link them from the overview.
- Treat existing installations as a separate compatibility gate: never run migration, permission changes, package updates or cleanup on a productive system as a test. Rehearse setup and full restore on an isolated copy before recommending an existing-install upgrade. A green CI run does not establish this release gate; record missing real-device checks honestly.
- Keep security invariants across UI, API and helpers: server-side session and CSRF checks for writes, no default credentials or persisted project passwords, and deployment/rollback limited to configured generated files. Preserve legacy output as the default when changing optional YAML output. See [the integrated architecture and release gates](docs/DEVELOPER_GUIDE.md#integrated-feature-upgrade-branch).
- For repository cleanup, check local references and links from open PRs before removing assets. Reuse an existing screenshot instead of committing an identical copy; fold short image descriptions into the existing guide instead of adding a Markdown sidecar. Keep source modules, installer helpers, security checks, golden files and regression tests needed for the integrated behavior. Preserve stable paths consumed by installations and APIs. Verify links and run the applicable core and browser suites after cleanup.

### Test Structure

- `tests/test_*.py` — Unit tests (root level)
- `tests/integration/` — Integration tests with golden file comparisons
- `tests/ui/` — Playwright browser tests against live Flask server
- `tests/fixtures/expected_output/` — Golden files for 3 projects: Charne, UploadJson, Mini

### Regenerate Golden Files

After modifying output logic, regenerate reference files:

```bash
python scripts/regenerate_golden.py
```

### CI Pipeline (GitHub Actions)

1. **Lint**: `black --check .` + `isort --check-only .` + `flake8 .`
2. **Core Tests**: Python 3.12 + 3.13 matrix on ubuntu-latest
3. **UI Tests**: Playwright with Chromium (depends on core tests passing)

## Critical Pitfalls

### 1. Module-level state in ets_to_openhab.py

`ets_to_openhab.py` uses 10+ module-level mutable globals (`floors`, `all_addresses`, `equipments`, etc.). These are set by `knxproject_to_openhab.main()` before calling `gen_building()`. The module is NOT reentrant. Always reset state in test `setup_method()`:

```python
def setup_method(self):
    ets_to_openhab.floors = []
    ets_to_openhab.all_addresses = []
    ets_to_openhab.used_addresses = []
    ets_to_openhab.equipments = {}
    ets_to_openhab.FENSTERKONTAKTE = []
    ets_to_openhab.PRJ_NAME = "Our Home"
```

### 2. config.py executes on import

`config.py` calls `main()` at module level. Every `import config` triggers file I/O, subprocess calls, and path detection. Tests that import any module depending on `config` will trigger this. Mock or patch before importing.

### 3. gen_building() is 500+ lines

The core generation function `ets_to_openhab.gen_building()` is a single 500+ line function with 3 nested sub-functions and a 3-pass loop (`for run in range(3)`). When modifying generation logic:
- Understand the pass ordering: pass 0/1 resolve multi-address components, pass 2 generates single-address items
- Run golden file regeneration after any change
- Test with all 3 golden projects (Charne, UploadJson, Mini)

### 4. Monkeypatch order matters

In `tests/test_web_ui_job_endpoints.py`, `builtins.open` must be monkeypatched BEFORE `importlib.import_module`. Reversed order causes `AttributeError: 'SimpleNamespace' object has no attribute 'open'` because pytest's monkeypatch resolves `builtins` via the mocked import.

### 5. ETS description tags

Group Address description fields in ETS support semicolon-separated tags:
`influx`, `debug`, `icon=pump`, `semantic=Projector`, `location`, `ignore`
Scene mapping: `1='Cooking', 2='TV'`

Processed by `ets_to_openhab.process_description()`.

### 6. DPT format mismatch

`ets_helpers.py` `get_dpt_from_dco()` returns `"5.001"` format, but `ets_to_openhab.py` has its own nested version returning `"DPST-5-1"` format. These are incompatible — be careful which one you use.

### 7. Template placeholders

Templates use simple string replacement:
- `items.template`: `###items###`
- `things.template`: `###things###`
- `sitemap.template`: `###sitemap###`

Keep template header/footer intact. Only modify the placeholder injection logic.

## Common Tasks

### Add a new DPT mapping

Edit `config.json` → `datapoint_mappings`. Add entry with `item_type`, `item_icon`, `semantic_info`, `alexa`, `homekit` fields.

### Change device detection rules

Edit `config.json` → `defines`. Modify suffix lists for `dimmer`, `switch`, `rollershutter`, `heating` etc.

### Add a new API endpoint

Edit `web_ui/backend/app.py`. When authentication is enabled, its `before_request` handler checks sessions and CSRF centrally; ensure a new route is covered by that policy and add tests for unauthenticated and invalid-CSRF requests when it writes state. Update `web_ui/api_schema.json`.

### Modify output generation

Edit `ets_to_openhab.py` → `gen_building()` for content, `export_output()` for file writing. Always regenerate golden files afterward.

## When to Ask the Human

Ask for a representative ETS address or project when device rules cannot be determined from existing fixtures. For generator, dependency or output-format changes, inspect the existing behavior, requirements and openHAB compatibility, then implement and test the authorized scope. Ask only when a required behavior or migration decision remains ambiguous. For global-state test failures, first check fixture and `setup_method()` resets.
