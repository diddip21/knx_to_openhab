# Copilot / AI Agent Instructions for knx_to_openhab

## Quick Summary

- **Entry point:** `knxproject_to_openhab.py` — parses KNX project, builds in-memory building model
- **Generator:** `ets_to_openhab.py` — consumes building model, writes OpenHAB files via `*.template` wrappers
- **Config:** `config.json` loaded/normalized by `config.py`
- **Web UI:** Flask backend (`web_ui/backend/app.py`) + vanilla JS frontend (`web_ui/static/app.js`)

## Data Flow

```
knxproject_to_openhab.py:
  XKNXProj(file) → create_building() → get_addresses() → put_addresses_in_building()

ets_to_openhab.py:
  gen_building() → 3-pass loop over addresses
    Pass 0-1: resolve multi-address components (dimmers, rollos, scenes)
    Pass 2: generate single-address items
  export_output() → apply templates → write files to openhab/
```

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `knxproject_to_openhab.py` | 789 | KNX parser, building hierarchy, address placement |
| `ets_to_openhab.py` | 1058 | Core generator: `gen_building()` (L34-849), `export_output()` (L929-1046) |
| `config.py` | 217 | Config loader. **Executes on import** — `main()` called at L202 |
| `config.json` | 500 | Detection rules, DPT mappings, regex patterns, output paths |
| `ets_helpers.py` | 173 | Testable helpers: `get_co_flags()`, `flags_match()`, `get_dpt_from_dco()` |
| `completeness.py` | 111 | Post-generation validation of Things files |
| `web_ui/backend/app.py` | 1071 | Flask routes, auth, SSE, 20+ API endpoints |
| `web_ui/backend/jobs.py` | 1233 | Job queue, staging/deploy, backup/rollback |
| `web_ui/backend/storage.py` | 147 | JSON persistence, atomic writes |
| `web_ui/backend/updater.py` | 260 | Git-based self-update via GitHub API |

## Conventions

- **Python 3.12+**, Black (line-length 100), isort (profile=black), flake8 (max 100)
- Conventional commits: `feat:`, `fix:`, `chore:`, `style:`
- Item naming: `i_` prefix + floor/room short names + shortened GA label
- `config.py` `normalize_string()` for all string comparisons
- `config.py` `special_char_map` for umlaut replacement (ä→ae, ö→oe, ü→ue, ß→ss)

## Testing

```bash
pytest -q -m "not ui" --ignore=tests/ui  # All core tests (excludes UI)
pytest tests/integration -v        # Integration tests
pytest tests/test_*.py -v          # Unit tests only
pytest --cov=. --cov-report=html   # With coverage
pytest tests/ui -v -o addopts=     # UI tests (needs Playwright + server)
python scripts/regenerate_golden.py  # Regenerate golden files after output changes
```

**CI pipeline:** Lint (black+isort+flake8) → Core Tests (Python 3.12+3.13) → UI Tests (Playwright)

## Pitfalls

1. **Global state** — `ets_to_openhab.py` uses 10+ module-level mutable globals. Reset in test `setup_method()`.
2. **config.py side effects** — `main()` runs on import. Mock before importing if needed.
3. **gen_building() complexity** — 500+ lines, 3 nested sub-functions, 3-pass loop. Run golden file regen after changes.
4. **Monkeypatch order** — In `test_web_ui_job_endpoints.py`, mock `builtins.open` BEFORE `importlib.import_module`.
5. **DPT format normalization** — Use the shared `ets_helpers.get_dpt_from_dco()`, which returns canonical `"DPST-5-1"`; do not duplicate it in the generator.
6. **ETS description tags** — Semicolon-separated in GA description: `influx`, `debug`, `icon=pump`, `semantic=Projector`, `ignore`
7. **Template placeholders** — `###items###`, `###things###`, `###sitemap###` in `*.template` files

## API Endpoints (Web UI)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/upload` | Upload `.knxproj`, create job |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/job/<id>` | Job details |
| GET | `/api/job/<id>/events` | SSE live log stream |
| POST | `/api/job/<id>/deploy` | Deploy staged files to live OpenHAB |
| POST | `/api/job/<id>/rollback` | Restore from backup |
| GET | `/api/job/<id>/diff` | Diff stats |
| GET | `/api/config` | Read config |
| POST | `/api/config` | Write config |
| POST | `/api/service/restart` | Restart systemd service |
| GET | `/api/version` | Current git version |
| GET | `/api/status` | Health check |

## When to Ask the Human

- `config.json` rules are ambiguous — ask for a sample ETS address/name
- Modifying `gen_building()` — confirm the 3-pass logic understanding
- Adding new dependencies — check `requirements.txt` first
- Changing output format — confirm OpenHAB compatibility
- Test failures involve global state — check `setup_method()` resets
