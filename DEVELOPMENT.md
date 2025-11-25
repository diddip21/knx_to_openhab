# Development Guide — KNX to OpenHAB Web UI

This guide helps you set up a local development environment to work on the KNX to OpenHAB Web UI.

> **Note:** For production installation on Raspberry Pi/DietPi, see [WEBUI_INSTALLATION.md](WEBUI_INSTALLATION.md)

---

## Prerequisites

- **Python 3.11+** (verify with `python --version` or `python3 --version`)
- **pip** (Python package manager)
- **git** (for cloning the repository)

---

## Quick Start

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

For development, you can create a custom config:

```bash
cp web_ui/backend/config.json web_ui/backend/config.dev.json
```

Edit `config.dev.json` to disable authentication for easier local testing:

```json
{
  "openhab_path": "openhab",
  "jobs_dir": "var/lib/knx_to_openhab",
  "backups_dir": "var/backups/knx_to_openhab",
  "bind_host": "127.0.0.1",
  "port": 5000,
  "auth": {
    "enabled": false
  },
  "retention": {
    "days": 14,
    "max_backups": 50,
    "max_backups_size_mb": 500
  }
}
```

### 4. Start Development Server

**Using Flask CLI** (recommended):
```bash
# Activate venv first (see step 1)
flask --app web_ui.backend.app:app run --debug
```

**Or using Python directly**:
```bash
python -m flask --app web_ui.backend.app:app run --debug
```

**Or run the app module**:
```bash
cd web_ui/backend
python -m app
```

---

## Project Structure

```
knx_to_openhab/
├── README.md                       # Main project readme
├── DEVELOPMENT.md                  # This file
├── WEBUI_INSTALLATION.md           # Production installation guide
├── requirements.txt                # Python dependencies
├── config.json                     # Main KNX parser configuration
├── config.py                       # Config loader
│
├── knxproject_to_openhab.py        # Core: KNX project parser
├── ets_to_openhab.py               # Core: OpenHAB file generator
│
├── web_ui/                         # Web UI application
│   ├── backend/
│   │   ├── app.py                  # Flask routes & SSE
│   │   ├── jobs.py                 # Job manager & backup logic
│   │   ├── storage.py              # JSON persistence
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
│   ├── knxui.service               # systemd unit
│   └── ...
│
├── scripts/                        # Development helper scripts
│   ├── dev-setup.ps1               # Windows setup
│   ├── dev-setup.sh                # Linux/macOS setup
│   ├── dev-run.ps1                 # Windows dev server
│   ├── dev-run.sh                  # Linux/macOS dev server
│   └── verify-setup.ps1/sh         # Setup verification
│
├── tests/                          # Test files
│   └── unit/                       # Unit tests
│
└── openhab/                        # OpenHAB output directory
    ├── items/
    ├── things/
    ├── sitemaps/
    └── ...
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
python knxproject_to_openhab.py --input project.knxproj
```

### 2. OpenHAB Generator (`ets_to_openhab.py`)

Generates OpenHAB configuration files from parsed KNX data:
- `items/*.items` - Item definitions
- `things/*.things` - Thing definitions
- `sitemaps/*.sitemap` - UI sitemaps
- `persistence/*.persist` - Persistence rules

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
curl -u admin:changeme http://localhost:5000/api/status
```

### Frontend Changes

1. **Edit HTML** in `web_ui/templates/index.html`
2. **Edit CSS** in `web_ui/static/style.css`
3. **Edit JS** in `web_ui/static/app.js`
4. **Refresh browser** (hard reload: Ctrl+Shift+R / Cmd+Shift+R)

### Config Changes

- **Web UI config**: `web_ui/backend/config.json`
- **KNX parser config**: `config.json` (root)

After changing config, restart the Flask server.

### Testing a KNX Project Locally

1. Place a test `.knxproj` or `.knxprojarchive` file in `tests/`
2. Start Flask server
3. Go to `http://localhost:5000`
4. Upload the file via the UI
5. Monitor live logs
6. Check generated files in `openhab/`

---

## Running Tests

### Unit Tests

```bash
# Activate venv first
python -m pytest tests/unit/
```

Or run a specific test:
```bash
python tests/unit/test_knxproject_to_openhab_Mayer.py
```

### Manual Testing Checklist

- [ ] Upload a KNX project file
- [ ] Verify live log streaming works
- [ ] Check generated OpenHAB files in `openhab/`
- [ ] Test backup creation
- [ ] Test rollback functionality
- [ ] Test service restart (if OpenHAB running)

---

## Troubleshooting

### Python Version Issues

**Error:** `python: command not found` or version < 3.11

**Solution:**
- Windows: Install Python from [python.org](https://www.python.org/downloads/)
- Linux: `sudo apt install python3.11` (Ubuntu/Debian)
- macOS: `brew install python@3.11`

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
  flask --app web_ui.backend.app:app run --port 5001
  ```

### Import Errors in `web_ui.backend.app`

**Error:** `ImportError: attempted relative import with no known parent package`

**Solution:**
Run Flask from the project root, not from `web_ui/backend/`:
```bash
cd /path/to/knx_to_openhab  # project root
flask --app web_ui.backend.app:app run
```

---

## Advanced Configuration

### Development Config File

Create `web_ui/backend/config.dev.json` for local overrides:

```json
{
  "bind_host": "127.0.0.1",
  "port": 5000,
  "auth": {
    "enabled": false
  }
}
```

Then modify `storage.py` to load `config.dev.json` if it exists.

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
| **Port** | 5000 | 8080 |
| **Host** | 127.0.0.1 | 0.0.0.0 |
| **Auth** | Optional | Enabled |
| **Auto-start** | Manual | systemd |
| **Logs** | Terminal | journalctl |

---

## Support

- **Main Docs**: [README.md](README.md)
- **Production Install**: [WEBUI_INSTALLATION.md](WEBUI_INSTALLATION.md)
- **Issues**: Open an issue on GitHub with logs and error messages

---

**Happy Coding!** 🚀
