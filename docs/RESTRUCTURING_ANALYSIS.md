# 📊 Repository Restructuring - Complete Dependency Analysis

**Status:** ✅ ANALYSIS COMPLETE - READY FOR MIGRATION  
**Date:** 2026-01-27  
**Branch:** `feature/professional-restructuring`

---

## 🎯 Executive Summary

This document provides a complete dependency analysis of the `knx_to_openhab` repository before undertaking professional restructuring. The analysis covers all Python modules, import dependencies, file paths, template loading mechanisms, and critical migration risks.

### Key Findings:
- **Total Python Modules:** 8 core modules + web_ui backend (8 files)
- **Critical Import Dependencies:** Identified and mapped
- **Template Loading:** Hardcoded relative paths (BREAKING on migration)
- **Migration Complexity:** Medium-High (requires careful phased approach)
- **Test Coverage:** Existing tests need migration from root

---

## 📁 Current Repository Structure

### Root Level Files
```
knx_to_openhab/
├── config.py                     (8.8 KB)  - ⚠️ AUTO-EXECUTES on import
├── ets_to_openhab.py            (46 KB)   - 🔴 MAIN ENTRY POINT, hardcoded templates
├── ets_helpers.py                (6 KB)   - ✅ Safe utility module
├── knxproject_to_openhab.py     (20 KB)   - 🔴 ENTRY POINT, modifies ets_to_openhab globals
├── utils.py                      (492 B)  - ✅ Safe utility module
├── config.json                   (13.6 KB) - Configuration file
├── items.template                (2 KB)   - ⚠️ Hardcoded path reference
├── things.template               (174 B)  - ⚠️ Hardcoded path reference
├── sitemap.template              (48 B)   - ⚠️ Hardcoded path reference
├── test_config_api.py            - Test (needs migration to tests/)
├── test_config_update.py         - Test (needs migration to tests/)
├── generate_openhab_tests.py     - Optional test utility
├── install.sh, update.sh, etc.   - Installation scripts
└── Dockerfile.test               - Testing container

Directories:
├── web_ui/                       - Flask web application
│   ├── backend/                  - Flask app (app.py, jobs.py, etc.)
│   ├── static/                   - Frontend assets
│   └── templates/                - HTML templates
├── tests/                        - Existing test directory
├── docs/                         - Documentation
├── openhab/                      - Sample output
├── installer/                    - Installation utilities
└── .github/workflows/            - CI/CD (if exists)
```

---

## 🔗 COMPLETE DEPENDENCY GRAPH

### Module Import Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                         IMPORT GRAPH                              │
└─────────────────────────────────────────────────────────────────┘

Level 0 (No Internal Dependencies - SAFE TO MOVE):
├── utils.py
│   └── Exports: get_datapoint_type(type_str)
│
└── ets_helpers.py
    └── Exports: get_co_flags(), flags_match(), get_dpt_from_dco()

Level 1 (Depends on Level 0):
└── config.py ⚠️ AUTO-EXECUTES
    ├── Imports: json, re, logging, subprocess, os, pathlib (stdlib only)
    ├── ⚠️ Calls main() on import (no __name__ guard)
    ├── Reads: config.json (current working directory)
    ├── Reads: web_ui/backend/config.json (fallback for openhab_path)
    ├── Exports:
    │   ├── config (dict) - Global configuration
    │   ├── datapoint_mappings (dict)
    │   └── normalize_string(text: str)
    └── Side Effects:
        ├── Detects OPENHAB_CONF via openhab-cli
        ├── Modifies paths in config dict
        └── Sets target_user, target_group

Level 2 (Main Generator - CRITICAL):
└── ets_to_openhab.py 🔴 ENTRY POINT
    ├── Imports:
    │   ├── from config import config, datapoint_mappings, normalize_string
    │   ├── from utils import get_datapoint_type
    │   ├── from ets_helpers import get_co_flags, flags_match, get_dpt_from_dco
    │   └── Standard: re, os, logging, shutil
    ├── ⚠️ HARDCODED TEMPLATE PATHS (Line 1133-1155):
    │   ├── open('things.template', 'r', encoding='utf8')
    │   ├── open('items.template', 'r', encoding='utf8')
    │   └── open('sitemap.template', 'r', encoding='utf8')
    ├── Global Variables (set by functions):
    │   ├── GWIP, B_HOMEKIT, B_ALEXA
    │   ├── floors, all_addresses, used_addresses
    │   ├── equipments, FENSTERKONTAKTE, PRJ_NAME
    │   └── ⚠️ Modified by knxproject_to_openhab.py!
    ├── Entry Points:
    │   ├── main(configuration=None) - Main generation function
    │   ├── gen_building() - Generates items/sitemap/things
    │   └── export_output() - Writes files to disk
    └── Used By:
        ├── knxproject_to_openhab.py (imports as module)
        └── web_ui/backend/jobs.py (imports main())

Level 3 (KNX Project Handler):
└── knxproject_to_openhab.py 🔴 CLI ENTRY POINT
    ├── Imports:
    │   ├── from config import config, normalize_string
    │   ├── import ets_to_openhab (whole module!)
    │   ├── from xknxproject.models.knxproject import KNXProject
    │   ├── from xknxproject.xknxproj import XKNXProj
    │   └── Standard: logging, re, json, argparse, pathlib
    ├── ⚠️ MODIFIES ets_to_openhab GLOBALS (Line 545-552):
    │   ├── ets_to_openhab.floors = house[0]["floors"]
    │   ├── ets_to_openhab.all_addresses = addresses
    │   ├── ets_to_openhab.GWIP = ip
    │   ├── ets_to_openhab.B_HOMEKIT = homekit_enabled
    │   ├── ets_to_openhab.B_ALEXA = alexa_enabled
    │   └── ets_to_openhab.PRJ_NAME = prj_name
    ├── Entry Points:
    │   └── main() - CLI entry point with argparse
    └── Used By:
        └── web_ui/backend/app.py (imports as 'knxproject_to_openhab')

Level 4 (Web Application):
└── web_ui/backend/app.py 🌐 FLASK APP
    ├── Imports:
    │   ├── from .jobs import JobManager
    │   ├── from .service_manager import restart_service, get_service_status
    │   ├── from .storage import load_config
    │   ├── from .updater import Updater
    │   └── Standard: Flask, werkzeug, os, sys, json, uuid, etc.
    ├── Dynamic Imports (Line 735, 975):
    │   ├── import importlib
    │   ├── knxmod = importlib.import_module('knxproject_to_openhab')
    │   └── ⚠️ Uses absolute import path!
    ├── Path Calculations:
    │   ├── project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    │   ├── ⚠️ Assumes web_ui/backend/app.py location!
    │   ├── main_config_path = os.path.join(project_root, 'config.json')
    │   └── openhab_path from backend config or defaults
    └── Entry Points:
        ├── Flask routes (@app.route decorators)
        └── if __name__ == '__main__': app.run()

Level 4 Support (Web Backend):
├── web_ui/backend/jobs.py
│   ├── ⚠️ Imports: knxproject_to_openhab (absolute)
│   ├── ⚠️ Path: project_root = Path(__file__).parent.parent.parent
│   └── Calls: knxproject_to_openhab.main() in subprocess
│
├── web_ui/backend/storage.py
│   └── Loads: web_ui/backend/config.json
│
├── web_ui/backend/service_manager.py
│   └── Manages systemd services
│
└── web_ui/backend/updater.py
    ├── Path: base_path (project root)
    └── Runs: update.sh script
```

---

## ⚠️ CRITICAL MIGRATION RISKS

### 1. 🔴 Template File Loading (HIGH RISK)

**Problem:**
```python
# Current code in ets_to_openhab.py (Line 1133-1155)
things_template = open('things.template','r', encoding='utf8').read()
items_template = open('items.template','r', encoding='utf8').read()
sitemap_template = open('sitemap.template','r', encoding='utf8').read()
```

**Impact:**
- Assumes templates are in **current working directory**
- Will **FAIL** when module is in `src/knx_to_openhab/`
- Breaks when installed via pip (files in site-packages)

**Solution:**
```python
# Option 1: Using importlib.resources (Python 3.9+)
from importlib.resources import files

def load_template(name):
    template_dir = files('knx_to_openhab').parent / 'templates'
    return (template_dir / f'{name}.template').read_text('utf8')

things_template = load_template('things')
items_template = load_template('items')
sitemap_template = load_template('sitemap')

# Option 2: Using pkg_resources (compatible with older Python)
import pkg_resources

def load_template(name):
    return pkg_resources.resource_string(
        'knx_to_openhab', 
        f'../templates/{name}.template'
    ).decode('utf8')
```

**Migration Steps:**
1. Create `load_template()` helper function
2. Replace all `open('*.template')` calls
3. Test with both local development and installed package

---

### 2. 🔴 config.py Auto-Execution (MEDIUM RISK)

**Problem:**
```python
# Current code in config.py (no guard)
main()  # Executes on import!
config['special_char_map'] = {...}
datapoint_mappings = config['datapoint_mappings']
```

**Impact:**
- Reads `config.json` on **every import**
- Side effects (subprocess calls, file reads) during import
- Hard to test in isolation
- Assumes `config.json` in current directory

**Solution:**
```python
# Add lazy loading
_config = None

def get_config():
    global _config
    if _config is None:
        _config = _load_config()
    return _config

def _load_config():
    # Current main() logic here
    ...
    return cfg

# For backwards compatibility
config = get_config()  # Still auto-loads, but cleaner

# Better: Use importlib.resources for config.json location
from importlib.resources import files
config_path = files('knx_to_openhab').parent / 'config.json'
```

---

### 3. 🔴 Absolute Import Paths in Web UI (HIGH RISK)

**Problem:**
```python
# web_ui/backend/app.py (Line 735, 975)
import importlib
knxmod = importlib.import_module('knxproject_to_openhab')  # ❌ Absolute

# web_ui/backend/jobs.py
import knxproject_to_openhab  # ❌ Absolute
```

**Impact:**
- Assumes `knxproject_to_openhab.py` is in Python path
- Will **FAIL** when file is moved to `src/knx_to_openhab/knxproject.py`
- Requires updating all import statements

**Solution:**
```python
# After migration:
import importlib
knxmod = importlib.import_module('knx_to_openhab.knxproject')

# OR (preferred):
from knx_to_openhab import knxproject
```

---

### 4. 🔴 Project Root Path Calculations (MEDIUM RISK)

**Problem:**
```python
# web_ui/backend/app.py (Line 46)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
# Assumes: web_ui/backend/app.py → ../../.. = root

# web_ui/backend/jobs.py
project_root = Path(__file__).parent.parent.parent
```

**Impact:**
- After migration: `src/knx_to_openhab/web_ui/backend/app.py`
- Path calculation becomes: `../../../../` instead of `../../../`
- config.json path breaks
- Installation scripts path breaks

**Solution:**
```python
# Use package-relative paths
from importlib.resources import files
project_root = files('knx_to_openhab').parent.parent

# OR: Store in package metadata
import knx_to_openhab
project_root = Path(knx_to_openhab.__file__).parent.parent
```

---

### 5. 🟡 Global Variable Modification (MEDIUM RISK)

**Problem:**
```python
# knxproject_to_openhab.py modifies ets_to_openhab globals
import ets_to_openhab
ets_to_openhab.floors = house[0]["floors"]
ets_to_openhab.all_addresses = addresses
ets_to_openhab.GWIP = ip
# ...
```

**Impact:**
- **Not thread-safe**
- Tight coupling between modules
- After renaming: `from knx_to_openhab import generator` needs update

**Solution:**
```python
# Better: Pass data as function parameters
from knx_to_openhab import generator

result = generator.main(
    configuration=config,
    floors=house[0]["floors"],
    all_addresses=addresses,
    gwip=ip,
    homekit_enabled=homekit_enabled,
    alexa_enabled=alexa_enabled,
    prj_name=prj_name
)

# OR: Use a context object
context = GeneratorContext(
    floors=house[0]["floors"],
    all_addresses=addresses,
    # ...
)
generator.main(context)
```

**Migration Impact:**
- Requires refactoring `ets_to_openhab.main()` signature
- Can maintain backwards compatibility with default values

---

## 🔧 REQUIRED IMPORT CHANGES

### Phase-by-Phase Import Updates

#### Phase 1: Utilities (Safe)
```python
# No changes needed - no internal imports
```

#### Phase 2: config.py → src/knx_to_openhab/config.py
```python
# File: src/knx_to_openhab/config.py
# NO INTERNAL IMPORTS - Safe to move

# But needs to find config.json:
from importlib.resources import files
config_path = files('knx_to_openhab').parent / 'config.json'
# OR keep in package data:
config_path = files('knx_to_openhab') / 'config.json'
```

#### Phase 3: ets_to_openhab.py → src/knx_to_openhab/generator.py
```python
# OLD IMPORTS:
from config import config, datapoint_mappings, normalize_string
from utils import get_datapoint_type
from ets_helpers import get_co_flags, flags_match, get_dpt_from_dco

# NEW IMPORTS:
from .config import config, datapoint_mappings, normalize_string
from .utils import get_datapoint_type
from .ets_helpers import get_co_flags, flags_match, get_dpt_from_dco

# TEMPLATE LOADING:
# OLD:
open('things.template', 'r', encoding='utf8')

# NEW:
from importlib.resources import files
def load_template(name):
    template_dir = files('knx_to_openhab').parent / 'templates'
    return (template_dir / f'{name}.template').read_text('utf8')
```

#### Phase 4: knxproject_to_openhab.py → src/knx_to_openhab/knxproject.py
```python
# OLD IMPORTS:
from config import config, normalize_string
import ets_to_openhab

# NEW IMPORTS:
from .config import config, normalize_string
from . import generator  # renamed from ets_to_openhab

# GLOBAL MODIFICATION (OLD):
ets_to_openhab.floors = house[0]["floors"]

# NEW (Better - pass as parameters):
generator.main(
    configuration=config,
    floors=house[0]["floors"],
    all_addresses=addresses,
    # ...
)

# OR (Backwards compatible):
generator.floors = house[0]["floors"]
```

#### Phase 5: web_ui/ → src/knx_to_openhab/web_ui/
```python
# File: src/knx_to_openhab/web_ui/backend/app.py

# OLD IMPORTS:
from .jobs import JobManager
import importlib
knxmod = importlib.import_module('knxproject_to_openhab')

# NEW IMPORTS:
from .jobs import JobManager
from ... import knxproject  # relative import from parent package
# OR:
import importlib
knxmod = importlib.import_module('knx_to_openhab.knxproject')

# PATH CALCULATION (OLD):
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
# web_ui/backend/app.py → ../../../ = root

# PATH CALCULATION (NEW):
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
# src/knx_to_openhab/web_ui/backend/app.py → ../../../../ = root

# BETTER:
from importlib.resources import files
project_root = files('knx_to_openhab').parent.parent
```

---

## 📋 MIGRATION CHECKLIST

### Pre-Migration (Analysis Phase)
- [x] Map all import dependencies
- [x] Identify template loading mechanisms
- [x] Identify path calculation logic
- [x] List all entry points
- [x] Identify global variable usage
- [ ] Review test files and their imports
- [ ] Check installation scripts for hardcoded paths

### Phase 0: Setup
- [x] Create feature branch
- [x] Create analysis document (this file)
- [ ] Create `src/` directory structure
- [ ] Create empty `__init__.py` files

### Phase 1: Package Structure
- [ ] Create `src/knx_to_openhab/__init__.py`
- [ ] Create `src/knx_to_openhab/__main__.py`
- [ ] Test: `python -m src.knx_to_openhab --help`

### Phase 2: Move Utilities (Low Risk)
- [ ] `git mv config.py src/knx_to_openhab/config.py`
- [ ] Update config.json path in config.py
- [ ] Test: `python -c "from src.knx_to_openhab.config import config; print('OK')"`
- [ ] `git mv utils.py src/knx_to_openhab/utils.py`
- [ ] Test: `python -c "from src.knx_to_openhab.utils import get_datapoint_type; print('OK')"`
- [ ] `git mv ets_helpers.py src/knx_to_openhab/ets_helpers.py`
- [ ] Test: `python -c "from src.knx_to_openhab.ets_helpers import get_co_flags; print('OK')"`
- [ ] Run: `pytest tests/ -v`

### Phase 3: Move Main Generator (High Risk)
- [ ] `git mv ets_to_openhab.py src/knx_to_openhab/generator.py`
- [ ] Update imports in generator.py (relative imports)
- [ ] Add `load_template()` function
- [ ] Replace all `open('*.template')` calls
- [ ] Test: `python -c "from src.knx_to_openhab.generator import main; print('OK')"`
- [ ] Run: `pytest tests/ -v`

### Phase 4: Move KNX Project Handler
- [ ] `git mv knxproject_to_openhab.py src/knx_to_openhab/knxproject.py`
- [ ] Update imports in knxproject.py
- [ ] Update `import ets_to_openhab` → `from . import generator`
- [ ] Update global variable assignments
- [ ] Test: `python -c "from src.knx_to_openhab.knxproject import main; print('OK')"`
- [ ] Run: `pytest tests/ -v`

### Phase 5: Move Web UI (High Risk)
- [ ] `git mv web_ui/ src/knx_to_openhab/web_ui/`
- [ ] Create `src/knx_to_openhab/web_ui/__init__.py`
- [ ] Update imports in all backend/*.py files
- [ ] Update path calculations (project_root)
- [ ] Update `knxproject_to_openhab` imports
- [ ] Test: `python -c "from src.knx_to_openhab.web_ui.backend.app import app; print('OK')"`
- [ ] Run web UI: `python -m src.knx_to_openhab.web_ui.backend.app`
- [ ] Run: `pytest tests/ -v`

### Phase 6: Move Templates
- [ ] `mkdir templates` (if not exists)
- [ ] `git mv *.template templates/`
- [ ] Verify template loading works
- [ ] Test generation: Run full workflow

### Phase 7: Consolidate Tests
- [ ] `git mv test_*.py tests/` (from root)
- [ ] Update imports in test files
- [ ] Create `tests/__init__.py` if needed
- [ ] Run: `pytest tests/ -v`

### Phase 8: Move Scripts
- [ ] Verify `scripts/` directory exists
- [ ] `git mv install.sh scripts/` (if not already there)
- [ ] `git mv update.sh scripts/` (if not already there)
- [ ] `git mv uninstall.sh scripts/` (if not already there)
- [ ] `git mv fix_permissions.sh scripts/` (if not already there)
- [ ] Update paths in scripts to new structure

### Phase 9: Modern Packaging
- [ ] Create `pyproject.toml`
- [ ] Update `requirements.txt` (production dependencies)
- [ ] Create `requirements-dev.txt` (dev dependencies)
- [ ] Create `.editorconfig`
- [ ] Test: `pip install -e .`
- [ ] Test: `knx-to-openhab --help`

### Phase 10: Update Installation Scripts
- [ ] Update `scripts/install.sh` for new structure
- [ ] Update `scripts/update.sh` for new structure
- [ ] Update `scripts/uninstall.sh`
- [ ] Test in Docker/VM

### Phase 11: Documentation
- [ ] Create `CHANGELOG.md`
- [ ] Update `README.md`
- [ ] Create `docs/installation.md`
- [ ] Create `docs/usage.md`
- [ ] Create `docs/development.md`
- [ ] Add migration guide

### Phase 12: CI/CD
- [ ] Create `.github/workflows/tests.yml`
- [ ] Test workflow locally (if possible)
- [ ] Push and verify CI passes

### Phase 13: Final Verification
- [ ] Run: `pip install -e ".[dev]"`
- [ ] Run: `pytest tests/ -v --cov=src/knx_to_openhab`
- [ ] Run: `knx-to-openhab --help`
- [ ] Run: `knx-to-openhab --version`
- [ ] Start web UI: `knx-to-openhab web`
- [ ] Test full workflow (upload .knxproj → generate → deploy)
- [ ] Run: `black --check src/ tests/`
- [ ] Run: `ruff check src/ tests/`
- [ ] Verify all links in documentation

---

## 🎯 SUCCESS CRITERIA

### Mandatory (Must Pass)
- ✅ All tests pass (`pytest tests/ -v`)
- ✅ CLI works: `knx-to-openhab --help`
- ✅ Web UI starts without errors
- ✅ Installation via `pip install -e .` works
- ✅ Templates load correctly from package data
- ✅ Configuration loads correctly
- ✅ Full workflow completes (upload → generate → deploy)
- ✅ No broken imports
- ✅ Documentation is complete and accurate

### Optional (Nice to Have)
- 🌟 Code coverage > 70%
- 🌟 All dependencies updated to latest stable versions
- 🌟 Code style passes (black, ruff)
- 🌟 CI/CD pipeline configured and passing
- 🌟 Docker image builds successfully

---

## 📝 IMPORTANT NOTES

### Backwards Compatibility

**Consider adding compatibility shims in root directory:**

```python
# File: config.py (root) - Compatibility shim
import warnings
warnings.warn(
    "Importing from root 'config' is deprecated. "
    "Use 'from knx_to_openhab.config import config' instead.",
    DeprecationWarning,
    stacklevel=2
)
from knx_to_openhab.config import *
```

This allows old code to work temporarily while users migrate.

### Testing Strategy

**After each phase:**
```bash
# 1. Run tests
pytest tests/ -v

# 2. Test imports
python -c "from knx_to_openhab import Config; print('✓ Import OK')"

# 3. Test CLI (once __main__.py exists)
python -m knx_to_openhab --help

# 4. Test web UI
python -m knx_to_openhab web &
curl -f http://localhost:8085
```

### Commit Strategy

**Commit after each successful phase:**
```bash
git add <changed files>
git commit -m "refactor(phase-N): <brief description>

- Moved X to Y
- Updated imports in Z
- Tests passing: <list critical tests>

Breaking changes: <if any>"
```

---

## 🚨 ROLLBACK PLAN

If issues arise during migration:

```bash
# 1. Check what changed
git status
git diff

# 2. Rollback last commit
git reset --hard HEAD~1

# 3. Or rollback to specific commit
git log --oneline
git reset --hard <commit-sha>

# 4. If needed, delete branch and start over
git checkout main
git branch -D feature/professional-restructuring
```

**Always commit working states!**

---

## 📞 Questions to Resolve

1. **Minimum Python version?** (Affects importlib.resources usage)
   - Python 3.7+: Use `importlib.resources` with backport
   - Python 3.9+: Use `importlib.resources.files()` directly
   - Python 3.11+: Can use newest API

2. **Template location?**
   - Option A: `templates/` in repository root (package data)
   - Option B: `src/knx_to_openhab/templates/` (inside package)
   - **Recommendation:** Option A (easier for users to customize)

3. **config.json location?**
   - Option A: Repository root (user-editable)
   - Option B: Inside package (read-only, requires config.json.example)
   - **Recommendation:** Option A (keep in root)

4. **Backwards compatibility period?**
   - Keep compatibility shims for 1-2 versions?
   - Document migration clearly in CHANGELOG?

5. **CI/CD provider?**
   - GitHub Actions (already has .github/)
   - Other?

---

**Analysis Complete! Ready to proceed with Phase 0 (Setup).**

---

*Last Updated: 2026-01-27*
