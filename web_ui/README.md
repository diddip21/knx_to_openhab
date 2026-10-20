# KNX → OpenHAB Web UI

Lightweight Flask web interface for `knxproject_to_openhab.py`. Upload KNX project files, preview the building structure, generate OpenHAB configuration, review diffs, and deploy — all from a browser.

## Quick Start

```bash
# On Raspberry Pi / DietPi (production)
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash

# Access: http://<pi-ip>:8085
# Default credentials: admin / logihome (change in Settings!)
```

## Architecture

```
web_ui/
├── backend/
│   ├── app.py              # Flask routes, auth, SSE (1071 lines)
│   ├── jobs.py             # Job queue, staging, deploy, backup (1233 lines)
│   ├── storage.py          # JSON persistence, atomic writes
│   ├── updater.py          # Git-based self-update via GitHub API
│   ├── service_manager.py  # systemd service control
│   ├── config.json         # Runtime config (auth, ports, retention)
│   └── gunicorn_conf.py    # Production gunicorn config
├── templates/
│   └── index.html          # Single-page application (368 lines)
├── static/
│   ├── app.js              # Frontend logic, SSE, diff viewer (1978 lines)
│   └── style.css           # CSS with custom properties (1892 lines)
└── api_schema.json         # API documentation
```

## Local Development

```bash
# Clone and set up
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Start dev server
flask --app web_ui.backend.app:app run --debug
# → http://localhost:5000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload `.knxproj` file, create job |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/job/<id>` | Get job details |
| GET | `/api/job/<id>/events` | SSE live log stream |
| GET | `/api/job/<id>/diff` | Diff stats for job files |
| POST | `/api/job/<id>/rerun` | Re-run job with same input |
| POST | `/api/job/<id>/deploy` | Deploy staged files to live OpenHAB |
| POST | `/api/job/<id>/rollback` | Restore from backup |
| DELETE | `/api/job/<id>` | Delete job |
| GET | `/api/job/<id>/preview` | Building structure preview |
| GET | `/api/file/preview` | Read file content (live/staged/backup) |
| GET | `/api/config` | Read main config.json |
| POST | `/api/config` | Write main config.json |
| GET | `/api/config/schema` | Return config JSON Schema |
| POST | `/api/project/preview` | Parse knxproj, return building tree |
| POST | `/api/service/restart` | Restart a systemd service |
| GET | `/api/service/<name>/status` | Check service status |
| GET | `/api/version` | Current git version info |
| GET | `/api/version/check` | Check GitHub for updates |
| POST | `/api/version/update` | Trigger self-update |
| GET | `/api/service/<openhab|evcc>/version` | Installed package and APT candidate |
| POST | `/api/service/updates/<refresh|openhab|evcc>` | Refresh package lists or update one package |
| GET | `/api/status` | Health check (no auth) |

Full schema: see `api_schema.json`.

### openHAB and evcc package updates

The Services panel compares the installed Debian package with the candidate from the local APT
package lists. Use **Paketlisten prüfen** to refresh those lists, then update either package
individually. The update follows the configured APT repository (including an evcc nightly
repository, if configured). Review the upstream release notes before a major upgrade. Manual,
Docker, and other non-APT installations are shown as unsupported; they are never modified.

The update installs the exact APT version shown in the confirmation. If the candidate changes
before installation, it aborts and asks you to check again. The update runs in the background.
The UI reports completion or failure; existing generated
openHAB configuration is not replaced by the Web UI. A personal Web UI password is required.
After upgrading an existing Web UI installation from a version before this feature, run
`cd /opt/knx_to_openhab && sudo bash installer/setup.sh` once to install the root-owned,
package-restricted update helper and its sudoers entries. This step is also performed by
`install.sh` on a new installation. The APT candidate can be newer than the version displayed
before refreshing the package lists; the selected package is the only one explicitly upgraded.

Example screens with illustrative versions:

![Both packages have updates](../docs/screenshots/issue-41-updates-available.png)

![evcc is not an APT package](../docs/screenshots/issue-41-no-apt-package.png)

## Configuration

Runtime config in `web_ui/backend/config.json`:

```json
{
  "openhab_path": "openhab",
  "jobs_dir": "var/lib/knx_to_openhab",
  "backups_dir": "var/backups/knx_to_openhab",
  "bind_host": "0.0.0.0",
  "port": 8085,
  "auth": {
    "enabled": true,
    "user": "admin",
    "password": "logihome"
  },
  "retention": {
    "days": 14,
    "max_backups": 50,
    "max_backups_size_mb": 500
  }
}
```

## Troubleshooting

```bash
# Check if server is running
curl http://localhost:8085/api/status

# View logs
sudo journalctl -u knxohui.service -f

# Restart service
sudo systemctl restart knxohui.service

# Check port
netstat -tulpn | grep 8085
```
