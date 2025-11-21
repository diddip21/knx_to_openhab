# Copilot / AI agent instructions for knx_to_openhab

Short summary
- Entry point: `knxproject_to_openhab.py` — parses a KNX project and builds an in-memory house model.
- Generator: `ets_to_openhab.py` — consumes the house model and writes OpenHAB `things`, `items`, `sitemaps`, `persistence`, `rules` using the `*.template` files.
- Configuration lives in `config.json` and is loaded/normalized by `config.py`.

Big picture (how data flows)
- `knxproject_to_openhab.py` parses a KNX file (via `xknxproject.XKNXProj`) → creates `building` via `create_building()` → extracts `addresses` via `get_addresses()` → `put_addresses_in_building()` to merge addresses into building structure.
- The finished `house` and `addresses` are assigned into module-level vars in `ets_to_openhab` (e.g. `ets_to_openhab.floors`, `ets_to_openhab.all_addresses`) and then `ets_to_openhab.main()` is called to produce files.
- `ets_to_openhab.gen_building()` performs a two-pass processing of addresses: first pass to resolve multi-address components (dimmers, rollershutters, scenes), second pass to generate remaining single-address items. This ordering is important — keep it when changing generation logic.

Key files and conventions (quick map)
- `config.json`: central; contains `regexpattern`, `defines` (switch/dimmer/rollershutter metadata), `datapoint_mappings`, and output paths like `items_path`, `things_path`. Edit this to change detection rules and output locations.
- `config.py`: loads/normalizes `config.json` and exposes `config`, `datapoint_mappings` and `special_char_map` (used to sanitize item names). Use `normalize_string()` for comparisons.
- `knxproject_to_openhab.py`: KNX parsing, name extraction helpers (`get_floor_name`, `get_room_name`) and placement logic (`place_address_in_building`, `place_address_by_device`). See `find_floors()` for recursion over nested ETS structures.
- `ets_to_openhab.py`: generator. Important parts: `get_co_by_functiontext()`, `get_address_from_dco()`, `process_description()` (parses ETS description tags like `influx`, `icon=pump`, `semantic=…`), `gen_building()` and `export_output()` which applies the templates `things.template`, `items.template`, `sitemap.template`.
- Templates: `items.template`, `things.template`, `sitemap.template` — these are small wrappers where the generated content is injected (`###items###`, `###things###`, `###sitemap###`). Keep templates intact to preserve header/footer formatting.

Project-specific patterns and expectations
- Item naming: generated item names use an `i_` prefix and combine floor/room short names and a shortened GA label (see `ets_to_openhab.py` item_name generation). The `special_char_map` in `config.py` ensures umlauts and special characters are replaced consistently.
- Regex-driven detection: many decisions rely on `config['regexpattern']` (e.g. `item_Room`, `item_Floor`). Changing these affects parsing throughout — run a full generation after adjustments.
- `defines` dict in `config.json`: contains suffix lists, `drop` lists and `change_metadata`. These are used heavily to detect multi-address components (dimmers, shutters, heaters) and to tweak generated metadata (icons, semantic tags, homekit/alexa hints).
- ETS description processing: `Description` fields in ETS may include semicolon-separated flags: `influx`, `debug`, `icon=...`, `semantic=...`, `location=...`, `ignore`. `process_description()` maps these to item metadata.

Integration points & dependencies
- External Python: code uses `xknxproject` to parse KNX projects. Ensure it's installed in the environment (`pip install xknxproject`).
- Templates and outputs: generator writes into paths set in `config.json` and uses `openhab/` as a recommended local output folder (there are sample `openhab/items/...` in the repo).
- HomeKit/Alexa: enabled by parsing `project['info']['comment']` (strings containing `homekit` or `alexa`) — generation adds `homekit`/`alexa` metadata accordingly.

Developer workflows (how to run locally)
- 1) Edit `config.json` to match your naming conventions and output paths.
- 2) Generate OpenHAB files from a KNX project (example using an existing JSON dump):
  - `python3 knxproject_to_openhab.py --file_path tests/Mayer.knxprojarchive.json --readDump`
  - Or point to the `.knxprojarchive` and optionally supply `--knxPW`.
- 3) After generation, outputs are written to the configured `things_path`, `items_path`, `sitemaps_path`, `influx_path`, `fenster_path` (see `config.json`).
- 4) Regenerate tests (optional): `python3 generate_openhab_tests.py` will create unit tests under `tests/unit/` based on current `openhab/` output. NOTE: the bundled test generation and generated tests contain Windows-style absolute paths — update the generated test paths or re-run the generator to produce repo-relative paths before running tests.

Testing and pitfalls
- The repo contains `tests/unit/test_knxproject_to_openhab_Mayer.py` which was auto-generated referencing `c:\Users\...` absolute paths — these will fail on Linux. Recommended: run `generate_openhab_tests.py` (or adjust it) to produce tests with repository-relative paths, or edit the test to use `openhab/...` paths.
- `generate_openhab_tests.py` currently uses a Windows venv path (`.venv/Scripts/python.exe`); for Linux edit it to use `sys.executable` or call the script directly with `python3`.

Small examples to copy/paste
- Run generator from a JSON dump:
  - `python3 knxproject_to_openhab.py --file_path tests/Mayer.knxprojarchive.json --readDump`
- Quick install of main dependency (if missing):
  - `python3 -m pip install xknxproject lark-parser`
- Regenerate tests (edit `generate_openhab_tests.py` first on Linux):
  - open `generate_openhab_tests.py` and replace the hardcoded `venv_python` with `sys.executable`, then run `python3 generate_openhab_tests.py`

When to ask the human
- If `config.json` rules are ambiguous (regex/suffix lists) ask for a sample ETS address/name to craft or refine matching rules.
- If generated tests are required to run in CI, ask whether you want repo-relative paths or platform-specific test variants.

If anything above is missing or you'd like it adapted to CI (GitHub Actions) or to generate tests with repo-relative paths automatically, tell me which option you prefer and I will update this file.
