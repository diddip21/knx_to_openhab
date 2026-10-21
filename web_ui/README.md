# KNX → OpenHAB Web UI

Lightweight Flask web interface for `knxproject_to_openhab.py`. Upload KNX project files, preview the building structure, generate OpenHAB configuration, review diffs, and deploy — all from a browser.

## Quick Start

```bash
# On Raspberry Pi / DietPi (production)
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash

# Access: http://<pi-ip>:8085 (or the configured bind address and port)
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
│   ├── config.json         # Local development defaults only
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

# Start local browser tests without production credentials
export FLASK_ENV=testing
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
| GET | `/api/status` | Health check (no auth) |

Full schema: see `api_schema.json`.

On an installed system, runtime settings live in `/etc/knx_to_openhab/config.json`,
generator rules live in `/var/lib/knx_to_openhab/generator.json`, and the Argon2id UI
password hash is stored in `/etc/knx_to_openhab/secrets.env`. Fresh installs
prompt for a unique password; existing user-chosen passwords are preserved during migration,
while the shipped default requires replacement. Jobs and uploads
live in `/var/lib/knx_to_openhab/jobs`, staging output in
`/var/lib/knx_to_openhab/staging`, and backup archives in
`/var/backups/knx_to_openhab`. The installer migrates existing files before
switching the application to these paths. The tracked `backend/config.json` is
only used for local development and must not be edited to configure production.

## Configuration

Production runtime config in `/etc/knx_to_openhab/config.json`:

```json
{
  "openhab_path": "openhab",
  "jobs_dir": "/var/lib/knx_to_openhab/jobs",
  "staging_dir": "/var/lib/knx_to_openhab/staging",
  "generated_dir": "/var/lib/knx_to_openhab/generated",
  "backups_dir": "/var/backups/knx_to_openhab",
  "bind_host": "0.0.0.0",
  "port": 8085,
  "auth": {
    "enabled": true,
    "user": "admin"
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

Deploy writes only the configured generator outputs (`items`, `things`,
`sitemaps`, `persistence`, `rules`, and optional YAML) plus the three generated
reports. Targets must be existing regular files inside the effective OpenHAB
configuration root. Symlinks and traversal paths are rejected. Rollback
restores those managed files from the selected full-tree backup and leaves
manually maintained files untouched.
