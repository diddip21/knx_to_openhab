# Development Guide — KNX to OpenHAB

This guide covers local development on the generator, CLI, and Web UI.

> **Note:** For production installation on Raspberry Pi/DietPi, see [Production Guide](PRODUCTION_GUIDE.md)

---

## Prerequisites

- **Python 3.12+** (verify with `python --version` or `python3 --version`)
- **pip** (Python package manager)
- **git** (for cloning the repository)

---

## Quick Start

> **Note:** The default pytest run selects core tests and excludes the `ui` marker. See **Running Tests** to run the Playwright suite explicitly.

### Windows

```powershell
# Clone repository (if not already done)
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab

# Run setup script
.\scripts\dev-setup.ps1

# Start development server
.\scripts\dev-run.ps1
```

### Linux / macOS

```bash
# Clone repository (if not already done)
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab

# Run setup script
chmod +x scripts/dev-setup.sh scripts/dev-run.sh
./scripts/dev-setup.sh

# Start development server
./scripts/dev-run.sh
```

The Web UI will be available at **`http://localhost:5000`**

---

## Testing `main` or `dev` in a Separate Checkout

The installed Web UI updater follows published stable releases. It does not
switch an installation to a moving `main` or `dev` branch. To try either branch,
run its development server from a separate Git worktree on a development
computer or disposable test host. Do not run this branch-test server on the
production Raspberry Pi: service controls in the UI address services on the
machine running the server.

On Linux or macOS:

```bash
git fetch origin
git worktree add --detach ../knxoh-test-main origin/main
# For the development branch, use:
# git worktree add --detach ../knxoh-test-dev origin/dev
cd ../knxoh-test-main
unset KNXOH_INSTALL_DIR KNXOH_CONFIG_DIR KNXOH_DATA_DIR KNXOH_BACKUP_DIR
export KNXOH_PATHS_FILE="$PWD/.test-paths-file-not-created"
./scripts/dev-setup.sh
./scripts/dev-run.sh
```

On Windows, use the same `git worktree add` command from PowerShell, then:

```powershell
cd ..\knxoh-test-main
Remove-Item Env:KNXOH_INSTALL_DIR,Env:KNXOH_CONFIG_DIR,Env:KNXOH_DATA_DIR,Env:KNXOH_BACKUP_DIR -ErrorAction SilentlyContinue
$env:KNXOH_PATHS_FILE = Join-Path $PWD ".test-paths-file-not-created"
.\scripts\dev-setup.ps1
.\scripts\dev-run.ps1
```

Use `origin/dev` and the matching worktree directory name instead when testing
that branch. The test server is available at `http://127.0.0.1:5000`; its
repository-local configuration, jobs, and generated files stay in that
worktree. `KNXOH_PATHS_FILE` points to a deliberately absent file so the
development process does not load the host's installed-system paths. Refresh a
worktree after fetching with
`git -C ../knxoh-test-main checkout --detach origin/main`. For `dev`, use
`git -C ../knxoh-test-dev checkout --detach origin/dev`. Stop its server, return
to the original checkout, and remove the test worktree with
`git worktree remove ../knxoh-test-main` (or `../knxoh-test-dev`).

---

## Manual Setup (Without Scripts)

### 1. Create Virtual Environment

**Windows:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Web UI (Optional)

For local development and browser tests, set `FLASK_ENV=testing`. This disables
authentication only for that explicitly marked test process; production does
not use this setting.

### 4. Start Development Server

**Using Flask CLI** (recommended):
```bash
# Activate venv first (see step 1)
export FLASK_ENV=testing
flask --app web_ui.backend.app:app run --debug
```

**Or using Python directly**:
```bash
FLASK_ENV=testing \
python -m flask --app web_ui.backend.app:app run --debug
```

**Or run the app module**:
```bash
cd web_ui/backend
export FLASK_ENV=testing
python -m app
```

---

## Project Structure

```
knx_to_openhab/
├── README.md                       # Main project readme
├── CONTRIBUTING.md                 # Contributing guidelines
├── AGENTS.md                       # AI agent instructions
├── requirements.txt                # Python dependencies
├── config.json                     # Main KNX parser configuration
├── config.py                       # Config loader (executes on import!)
│
├── knxproject_to_openhab.py        # Core: KNX project parser
├── ets_to_openhab.py               # Core: OpenHAB file generator
├── ets_helpers.py                  # Extracted helper functions
├── completeness.py                 # Post-generation validation
├── utils.py                        # Shared utilities
│
├── web_ui/                         # Web UI application
│   ├── backend/
│   │   ├── app.py                  # Flask routes & SSE
│   │   ├── jobs.py                 # Job manager & backup logic
│   │   ├── storage.py              # JSON persistence
│   │   ├── updater.py              # Git-based self-update
│   │   ├── service_manager.py      # systemctl wrapper
│   │   └── config.json             # Web UI config
│   ├── templates/
│   │   └── index.html              # Main UI template
│   └── static/
│       ├── app.js                  # Frontend logic
│       └── style.css               # Styling
│
├── installer/                      # Production installation
│   ├── setup.sh                    # systemd installer (Linux)
│   ├── backup_cleanup.sh           # Cleanup script
│   ├── knxohui.service             # systemd unit
│   └── ...
│
├── scripts/                        # Development helper scripts
│   ├── dev-setup.ps1               # Windows setup
│   ├── dev-setup.sh                # Linux/macOS setup
│   ├── dev-run.ps1                 # Windows dev server
│   ├── dev-run.sh                  # Linux/macOS dev server
│   ├── regenerate_golden.py        # Golden file regeneration
│   └── verify-setup.ps1/sh         # Setup verification
│
├── tests/                          # Test files
│   ├── integration/                # Integration tests
│   ├── ui/                         # UI tests (Playwright)
│   ├── fixtures/                   # Test data and golden files
│   ├── conftest.py                 # Shared fixtures
│   └── test_*.py                   # Unit tests
│
├── docs/                           # Documentation
│   ├── USER_GUIDE.md               # End-user guide
│   ├── DEVELOPER_GUIDE.md          # This file
│   ├── PRODUCTION_GUIDE.md         # Production installation
│   └── images/                     # Screenshots
│
└── openhab/                        # Generated OpenHAB output
    ├── items/
    ├── things/
    ├── sitemaps/
    ├── persistence/
    └── yaml/                       # Optional openHAB 5.2 model
```

---

## Core Components

### 1. KNX Parser (`knxproject_to_openhab.py`)

Parses `.knxproj`, `.knxprojarchive`, or `.json` files and extracts:
- Building structure (floors, rooms)
- Group addresses with data point types
- Device communication objects
- Semantic metadata

**Usage:**
```bash
python knxproject_to_openhab.py --file_path project.knxproj
# For a password-protected project:
python knxproject_to_openhab.py --file_path project.knxproj --knxPW "password"
```

If `--file_path` is omitted, the CLI opens a file picker when Tk is available.

### 2. OpenHAB Generator (`ets_to_openhab.py`)

Generates OpenHAB configuration files from parsed KNX data. The default
`output_format` is `legacy`; its configured paths default to:

- `openhab/items/knx.items` — Item definitions
- `openhab/things/knx.things` — KNX Thing definitions
- `openhab/sitemaps/knx.sitemap` — Sitemap
- `openhab/persistence/influxdb.persist` — Persistence rules

Setting `output_format` to `yaml` writes the combined openHAB 5.2 model to
`openhab/yaml/knx.yaml` instead of the three legacy model files. Persistence
remains a separate text file. The paths can be changed in `config.json` or
through Web UI settings.

### 3. Web UI Backend (`web_ui/backend/`)

Flask application providing:
- **RESTful API** for job management
- **SSE (Server-Sent Events)** for live log streaming
- **Backup & Rollback** functionality
- **Service management** (restart OpenHAB)

**Key files:**
- `app.py` - Flask routes, authentication, SSE endpoints
- `jobs.py` - Job creation, execution, backup management
- `storage.py` - JSON-based persistence for jobs
- `service_manager.py` - systemctl interaction

### 4. Web UI Frontend (`web_ui/templates/`, `web_ui/static/`)

Vanilla HTML/CSS/JavaScript interface:
- No build process required
- No external dependencies
- Pure EventSource API for SSE

---

## Common Development Tasks

### Backend Changes

1. **Modify Flask routes** in `web_ui/backend/app.py`
2. **Restart Flask server** (auto-reload enabled in debug mode)
3. **Test API** with browser DevTools or `curl`

Example:
```bash
curl http://127.0.0.1:5000/api/status
```

### Frontend Changes

1. **Edit HTML** in `web_ui/templates/index.html`
2. **Edit CSS** in `web_ui/static/style.css`
3. **Edit JS** in `web_ui/static/app.js`
4. **Refresh browser** (hard reload: Ctrl+Shift+R / Cmd+Shift+R)

### Config Changes

- **Web UI config**: `web_ui/backend/config.json`
- **KNX parser config**: `config.json` (root)

These are the repository-local development files. In an installed system,
`KNXOH_CONFIG_DIR` from `/etc/knx_to_openhab/paths.env` points to persistent
Web UI settings in `config.json`; credentials are kept in `secrets.env`.
Generator rules are stored in `/var/lib/knx_to_openhab/generator.json` with
jobs and staging. Backups are under `/var/backups/knx_to_openhab`. The installer
migrates the old files and the API saves generator settings to the external
file. Restart the Flask server after changing local development config.

### Testing a KNX Project Locally

1. Place a test `.knxproj` or `.knxprojarchive` file in `tests/`
2. Start Flask server
3. Go to `http://localhost:5000`
4. Upload the file via the UI
5. Monitor live logs
6. Check generated files in `openhab/`

---

## Running Tests

The test suite has core tests and Playwright UI tests. The default pytest
configuration excludes the UI suite; run it separately when Chromium is
installed.

### Prerequisites

```bash
# Activate venv (Windows)
.\.venv\Scripts\Activate.ps1

# Activate venv (Linux/macOS)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Core Tests (default)

The default pytest config excludes UI tests, matching the CI core-test job.

```bash
pytest -q
```

**Run integration-only:**
```bash
pytest tests/integration -v
```

### UI Tests (optional)

UI tests use Playwright and start an isolated local Flask server on **8085**
with authentication disabled. No separately running development server is needed.

```bash
pip install pytest-playwright
python -m playwright install chromium

# Select the Playwright tests explicitly; this overrides the default core marker
pytest tests/ui -v -m ui
```

### Core Test Coverage

```bash
pytest -q --cov=. --cov-report=html
```

The Playwright suite is run separately with the UI command above.

### Generating Golden Files

Golden files are reference outputs used for regression testing.

```bash
python scripts/generate_golden_files.py --project tests/MyProject.knxproj.json --name MyProject
python scripts/generate_golden_files.py --project tests/Charne.knxproj.json --name Charne --force
```

### Manual Testing Checklist

- [ ] Upload a KNX project file via Web UI
- [ ] Verify live log streaming works
- [ ] Check generated OpenHAB files in `openhab/`
- [ ] Test backup creation
- [ ] Test rollback functionality
- [ ] Test service restart (if OpenHAB running)

---

## Troubleshooting

### Python Version Issues

**Error:** `python: command not found` or version < 3.12

**Solution:**
- Windows: Install Python from [python.org](https://www.python.org/downloads/)
- Linux: `sudo apt install python3.12` (Ubuntu/Debian)
- macOS: `brew install python@3.12`

### Virtual Environment Not Activating

**Windows PowerShell execution policy:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Linux/macOS permissions:**
```bash
chmod +x .venv/bin/activate
source .venv/bin/activate
```

### Flask Module Not Found

**Error:** `ModuleNotFoundError: No module named 'flask'`

**Solution:**
```bash
# Ensure venv is activated (prompt should show (.venv))
pip install -r requirements.txt
```

### Port Already in Use

**Error:** `Address already in use` on port 5000

**Solution:**
- Kill existing Flask process
- Or use a different port:
  ```bash
  FLASK_ENV=testing flask --app web_ui.backend.app:app run --port 5001
  ```

### Import Errors in `web_ui.backend.app`

**Error:** `ImportError: attempted relative import with no known parent package`

**Solution:**
Run Flask from the project root, not from `web_ui/backend/`:
```bash
cd /path/to/knx_to_openhab  # project root
FLASK_ENV=testing flask --app web_ui.backend.app:app run
```

---

## Advanced Configuration

### Local and installed configuration

Local development uses the repository's `web_ui/backend/config.json` for Web UI
defaults and the root `config.json` for generator settings. The application does
not load a `config.dev.json` override. Set `FLASK_ENV=testing` only for local
tests that need authentication disabled.

An installed system stores Web UI settings under `/etc/knx_to_openhab/` and
generator rules under `/var/lib/knx_to_openhab/generator.json`. The installer
records the active paths in `/etc/knx_to_openhab/paths.env`; do not edit the
repository defaults to change production settings.

### Debug Logging

Enable verbose logging in `app.py`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Hot Reload for Frontend

Flask's debug mode watches Python files, but not templates/static by default. For instant updates:

1. Use browser DevTools with "Disable cache"
2. Or install `flask-live-reload` (optional)

---

## Contributing Workflow

1. **Create a feature branch**
   ```bash
   git checkout -b feature/my-improvement
   ```

2. **Make changes** and test locally

3. **Commit with clear messages**
   ```bash
   git add .
   git commit -m "Add feature: XYZ"
   ```

4. **Push and create pull request**
   ```bash
   git push origin feature/my-improvement
   ```

---

## Production vs Development Differences

| Aspect | Development | Production |
|--------|-------------|------------|
| **Environment** | Windows/macOS/Linux | Raspberry Pi / DietPi |
| **Python Env** | `.venv` in project | `/opt/knx_to_openhab/venv` |
| **Server** | Flask dev server | systemd service |
| **Port** | 5000 | 8085 |
| **Host** | 127.0.0.1 | 127.0.0.1 |
| **Auth** | Optional | Enabled |
| **Auto-start** | Manual | systemd |
| **Logs** | Terminal | journalctl |

---

## Support

- **Main Docs**: [README.md](../README.md)
- **Production Install**: [Production Guide](PRODUCTION_GUIDE.md)
- **Issues**: Open an issue on GitHub with logs and error messages

---

**Happy Coding!** 🚀
