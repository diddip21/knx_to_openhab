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
      gen_building()         → generates items/things/sitemap strings (500+ lines)
      export_output()        → writes files using *.template wrappers
  → openhab/ output directory
      knx.items, knx.things, knx.sitemap, influxdb.persist
```

## Key Files

| File | Purpose |
|------|---------|
| `knxproject_to_openhab.py` | Entry point: parses `.knxproj`, builds building hierarchy, calls generator (789 lines) |
| `ets_to_openhab.py` | Core generator: `gen_building()` produces items/things/sitemap strings, `export_output()` writes files (1058 lines) |
| `config.json` | Central config: regex patterns, device detection rules, datapoint mappings, output paths (500 lines) |
| `config.py` | Loads `config.json`, normalizes values, detects OpenHAB paths. **Executes on import** — side effects at module level |
| `utils.py` | Single helper: `get_datapoint_type()` |
| `ets_helpers.py` | Extracted helpers: `get_co_flags()`, `flags_match()`, `get_dpt_from_dco()` |
| `completeness.py` | Post-generation validation: checks Things for missing required channels |
| `*.template` | Output wrappers: `items.template`, `things.template`, `sitemap.template` — use `###items###` placeholders |
| `web_ui/backend/app.py` | Flask routes, auth, SSE, 20+ endpoints (1071 lines) |
| `web_ui/backend/jobs.py` | Job queue, staging/deploy, backup/rollback (1233 lines) |
| `web_ui/backend/storage.py` | JSON persistence, atomic file writes |
| `web_ui/backend/updater.py` | Git-based self-update via GitHub API |
| `web_ui/backend/service_manager.py` | systemd service control |
| `web_ui/static/app.js` | Frontend SPA: vanilla JS, no framework (1978 lines) |

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
# All core tests (default, excludes UI tests)
pytest -q

# Specific test groups
pytest tests/integration -v
pytest -m unit
pytest -m integration

# With coverage
pytest --cov=. --cov-report=html

# UI tests (requires Playwright + running server)
pytest tests/ui -v -o addopts=
```

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

`config.py` calls `main()` at module level (line 202). Every `import config` triggers file I/O, subprocess calls, and path detection. Tests that import any module depending on `config` will trigger this. Mock or patch before importing.

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

Edit `web_ui/backend/app.py`. Follow existing patterns: Flask route, auth via `@require_auth`, JSON response. Update `web_ui/api_schema.json`.

### Modify output generation

Edit `ets_to_openhab.py` → `gen_building()` for content, `export_output()` for file writing. Always regenerate golden files afterward.

## When to Ask the Human

- If `config.json` rules are ambiguous — ask for a sample ETS address/name
- If modifying `gen_building()` — confirm understanding of the 3-pass logic
- If adding new dependencies — confirm they're needed and check `requirements.txt`
- If changing output file format — confirm compatibility with OpenHAB
- If test failures involve global state — check if `setup_method()` resets are needed
