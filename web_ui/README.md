# KNX → OpenHAB Web UI

Lightweight Flask web interface for `knxproject_to_openhab.py`. Upload KNX project files, preview the building structure, generate OpenHAB configuration, review diffs, and deploy — all from a browser.

## Quick Start

```bash
# On Raspberry Pi / DietPi (production)
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash

# Default access on the Pi: http://127.0.0.1:8085
# Remote access: use an SSH tunnel or explicitly configure a LAN bind / HTTPS proxy.
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
After upgrading an existing Web UI installation from a version before this feature, use the
release-aware installer as a regular user with `sudo` access (`install.sh --update`) to migrate
the installation and add the root-owned, package-restricted update helper and its sudoers entries.
Do not execute a release-owned `setup.sh` directly as root. This migration is also performed by
`install.sh` on a new installation. The APT candidate can be newer than the version displayed
before refreshing the package lists; the selected package is the only one explicitly upgraded.

Example screens with illustrative versions:

![Both packages have updates](../docs/screenshots/issue-41-updates-available.png)

![evcc is not an APT package](../docs/screenshots/issue-41-no-apt-package.png)

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
  "bind_host": "127.0.0.1",
  "port": 8085,
  "trusted_proxy_hops": 0,
  "session_max_age_seconds": 43200,
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

The default binds only to the local machine. Setup asks before retaining a legacy
LAN-wide bind. To allow direct LAN access, deliberately set `bind_host` to the
device's private interface address and restart the service. For HTTPS, keep the
application on loopback behind a reverse proxy and set `trusted_proxy_hops` to
the exact number of trusted proxies (usually `1`). The proxy must set
`X-Forwarded-Proto`; cookies are marked `Secure` when the request is recognized
as HTTPS. Write API requests require the signed-in session cookie and
`X-CSRF-Token` header.

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

## Verified release updates (API compatibility)

`POST /api/version/update` still accepts no body (stable). Optional JSON is exactly
`{"channel":"stable"}` or `{"channel":"prerelease"}`; `{}` also means stable.
Unknown fields, duplicate keys, invalid channels and non-JSON/malformed bodies
return 400 before any effects, including Windows simulation. Existing login/CSRF
and maintenance leases remain required. Busy submissions/active work return 409;
unavailable legacy/worker installations and acknowledgement timeout return an
actionable error without a shell/Git fallback. Existing `status`/`message` success
and `error` failure fields are retained. Windows retains `status: simulated`.

`status: updating` means the root coordinator **claimed this request**, not that
the update completed. The unit runs independently of the UI; inspect the existing
`GET /api/version/log` (`{"log":"..."}`) for its bounded, sanitized root-authored
projection outside releases. Timeouts retain the uncertain request; do not delete
locks or journal data to force another attempt. Use verified administrator
bootstrap/repair for one-time setup; interrupted claims require installed offline
recovery before repair. See `installer/README.md` for the service-context wrapper.

`GET /api/version/check[?channel=stable|prerelease]` checks supported GitHub release
assets, not branch commits. Stable is default; explicit prerelease chooses the
highest genuine prerelease SemVer, not a newer stable release. Equal precedence,
build-metadata-only differences and older releases do not advertise updates.
Metadata/network/unknown local VERSION errors set `update_available: false` with
`error`, not a claim that the installation is current. Existing compatibility
commit/date/branch/repository fields remain, with `unknown` commits when artifact
metadata is absent; versions are never fabricated commit hashes. Machine-readable
`current_version`/`latest_version` fields are additive; no visual UI change is made.
