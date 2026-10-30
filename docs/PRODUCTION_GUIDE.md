# Production Installation Guide — KNX to OpenHAB

## Overview

A lightweight, browser-based web interface to execute the KNX-to-OpenHAB generator on a Raspberry Pi (DietPi) without Docker. Includes real-time progress streaming, automatic backups, rollback capability, retention policies, and password-based browser sessions.

**Technology Stack:**
- **Backend:** Flask (Python) with Server-Sent Events (SSE) for live updates
- **Frontend:** Vanilla HTML/CSS/JavaScript (no external dependencies)
- **Installation:** Simple bash script, systemd service, no Docker required
- **OS Target:** DietPi / Raspberry Pi (Ubuntu compatible)

---

## Features

### Core Functionality
✅ **Upload KNX Projects** — Accept `.knxproj`, `.knxprojarchive`, or `.json` dumps  
✅ **Real-time Progress** — Live log streaming via Server-Sent Events (SSE)  
✅ **Automatic Backups** — Full tar.gz snapshot before each generation  
✅ **Rollback Capability** — Restore any previous backup in one click  
✅ **Retention Policies** — Auto-cleanup by age (days), count (max backups), and size (MB)  
✅ **Service Management** — Restart OpenHAB from the UI  
✅ **Protected Web Sessions** — Argon2id credentials, CSRF protection, session expiry and logout
✅ **Job History** — Persistent JSON storage of all jobs and metadata  

### UI Dashboard
- **Upload Form** with drag-and-drop-capable file input
- **Job List** with status badges (running, completed, failed)
- **Job Details** panel showing metadata, backup list, and logs
- **Rollback Dialog** to select and restore previous backups
- **Service Control** buttons to restart OpenHAB
- **Auto-refresh** of job list every 5 seconds
- **Professional styling** with responsive layout

---

## Installation (DietPi / Raspberry Pi)

### Prerequisites
- DietPi installed on Raspberry Pi
- OpenHAB already installed and running (or will be added later)
- SSH access to the Pi
- `git` and `python3` available

### Step 1: One-Command Installer

Run the following command to install or update the application:

```bash
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash
```

The installer will automatically:
1.  Check for system dependencies
2.  Create/Update `/opt/knx_to_openhab`
3.  Migrate settings, jobs, and backups outside the application tree
4.  Setup the service user and exact OpenHAB output permissions
5.  Install systemd services and restricted sudoers policy
6.  Print the access URL

The default external paths are `/etc/knx_to_openhab` for settings and secrets,
`/var/lib/knx_to_openhab` for jobs and staging, and
`/var/backups/knx_to_openhab` for archives. Existing configuration and user data
are copied before the new paths are activated. Active values are recorded in
`/etc/knx_to_openhab/paths.env`.

### Step 2: Verify Installation

```bash
# Check services
sudo systemctl status knxohui.service
sudo systemctl status knxohui-backup-cleanup.timer

# View service logs
sudo journalctl -u knxohui.service -f

# Verify web server is running
curl http://localhost:8085/api/status
```

### Step 3: Verify migrated settings and data

The setup step preserves existing user-chosen logins and stores their Argon2id password
hashes in `/etc/knx_to_openhab/secrets.env` with mode `0640`. A legacy shipped default
is discarded and setup prompts for a replacement. A fresh install also prompts for a
unique password; no default password is shipped. Runtime settings are in
`/etc/knx_to_openhab/config.json`; generator rules edited through the Settings
screen are in `/var/lib/knx_to_openhab/generator.json`. Jobs and backups remain
available after migration:

```bash
sudo cat /etc/knx_to_openhab/paths.env
sudo ls -la /var/lib/knx_to_openhab/jobs /var/backups/knx_to_openhab
```

To rotate the password without editing tracked configuration or exposing it in
shell history, run:

```bash
sudo /opt/knx_to_openhab/venv/bin/python \
  /usr/local/libexec/knx_to_openhab/set_ui_password.py
sudo systemctl restart knxohui.service
```

The root-owned helper prompts twice, stores an Argon2id hash in the configured
secrets file, and preserves other secret values.

### Recovering from a failed first update

If the Web UI reports that a migrated password hash is required, connect to the
device through an interactive SSH session (for example, `ssh -t <user>@<pi>`)
and run:

```bash
cd /opt/knx_to_openhab
sudo bash installer/setup.sh
```

Setup checks for the password prompt before it stops services or changes packages
and runtime data. It preserves a user-chosen password; if the old shipped default
was still in use, setup asks you to choose a new password. If setup fails after
stopping services, it attempts to restart the services that were active before
migration. Retry the Web UI update after setup completes.

The updater checks that `knxohui.service` stays active across three checks after
restart. If the updated service fails to start or remain active, it restores the
previous application commit and dependencies, then attempts to restart that
version. Check recovery with `sudo systemctl status knxohui.service` and
`sudo journalctl -u knxohui.service -n 100 --no-pager`.

### Uninstallation
To completely remove the application, use the uninstaller script:
```bash
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash
```
This will stop services, remove the installation directory, remove the service user, and clean up logs/backups.

---

## Usage

### Access the Web UI

By default, the Web UI listens only on the Raspberry Pi itself. Open it locally or use an SSH tunnel:
```
http://127.0.0.1:8085
```

For example, from your workstation run `ssh -L 8085:127.0.0.1:8085 <user>@<pi-ip>` and
then open `http://127.0.0.1:8085`. Setup asks before retaining a legacy binding that
allows LAN access. You can also deliberately set `bind_host` to a private interface
address in `/etc/knx_to_openhab/config.json`, then restart `knxohui.service`.

Sign in with the Web UI username and password configured during installation. The
browser keeps a revocable session cookie; write requests include a CSRF token.

### Upload and Process a KNX Project

1. **Click "Upload KNX Project"** and select a `.knxproj`, `.knxprojarchive`, or `.json` file
2. **Wait for processing** — see live logs in the "Live Log" section
3. **Monitor progress** — status updates show parsing, building, generation steps
4. **View completion** — job status changes to "completed" or "failed"

### View Job History

- **Jobs panel** lists all previous jobs with timestamps and status
- **Click "Details"** to see full job metadata, backup list, and logs
- **Auto-refresh** happens every 5 seconds

### Rollback to a Previous Backup

1. **Find the job** you want to rollback (can be any completed job)
2. **Click "Rollback"** button (only appears if backups exist)
3. **Select a backup** from the dropdown (shows timestamp)
4. **Confirm** — generated files are restored; manually maintained OpenHAB configuration remains unchanged

### Restart OpenHAB

1. **Go to "Services"** section at the bottom
2. **Click "Restart OpenHAB"** button
3. **Wait for confirmation** — shows if restart was successful

---

## Configuration

### Main Config File
Location: `/etc/knx_to_openhab/config.json`

```json
{
  "openhab_path": "openhab",                    // Where OpenHAB files are (relative to base)
  "jobs_dir": "/var/lib/knx_to_openhab/jobs",   // Job history + uploads
  "staging_dir": "/var/lib/knx_to_openhab/staging",
  "generated_dir": "/var/lib/knx_to_openhab/generated",
  "backups_dir": "/var/backups/knx_to_openhab", // Backup tar.gz files
  "bind_host": "127.0.0.1",
  "port": 8085,
  "trusted_proxy_hops": 0,
  "session_max_age_seconds": 43200,
  "auth": {
    "enabled": true,
    "user": "admin"
  },
  "retention": {
    "days": 14,                                  // Delete backups older than N days
    "max_backups": 50,                           // Keep maximum N backup files
    "max_backups_size_mb": 500                   // Maximum total backup size in MB
  }
}
```

### Retention Policy

Backups are cleaned up in this order:
1. **By age** — delete backups older than `days`
2. **By count** — keep only the newest `max_backups` files
3. **By size** — trim oldest backups until total size < `max_backups_size_mb`

Cleanup happens:
- **Immediately after** each new backup is created
- **Daily** via systemd timer (`backup-cleanup.timer`)
- **Daily** via systemd timer (`knxohui-backup-cleanup.timer`)
- **Manually** by running:
    sudo systemctl start knxohui-backup-cleanup.service
  ```bash
  sudo systemctl start backup-cleanup.service
  ```

---

## API Reference

### Endpoints (JSON)

Browser endpoints require a signed-in session unless `auth.enabled` is `false`.
The health endpoint `/api/status` remains public. For API writes, send the
`X-CSRF-Token` header using the value exposed in the signed-in page's
`csrf-token` meta tag. The browser UI does this automatically.

#### `POST /api/upload`
Upload a KNX project file.

**Request:**
```
Content-Type: multipart/form-data
Cookie: knx_session=…
X-CSRF-Token: <csrf-token>
File field: "file" (binary)
```

**Response:**
```json
{
  "id": "job-uuid",
  "name": "project.knxproj",
  "status": "running",
  "created": 1234567890,
  "input": "path/to/uploaded/file",
  "log": [],
  "backups": []
}
```

#### `GET /api/jobs`
List all jobs.

**Response:**
```json
[
  {
    "id": "job-uuid",
    "name": "project.knxproj",
    "status": "completed",
    "created": 1234567890,
    "backups": [
      {
        "name": "job-uuid-20251122-143022.tar.gz",
        "path": "var/backups/knx_to_openhab/...",
        "ts": "20251122-143022"
      }
    ]
  }
]
```

#### `GET /api/job/<job_id>`
Get full details of a specific job.

**Response:** Same as single job object above.

#### `GET /api/job/<job_id>/events`
Stream job progress as Server-Sent Events.

**Events:**
```
data: {"type": "info", "message": "start in-process generation"}
data: {"type": "backup", "message": "backup created: ..."}
data: {"type": "log", "message": "parsed knxproj"}
data: {"type": "status", "message": "completed"}
event: done
data: {"status": "done"}
```

#### `POST /api/job/<job_id>/rollback`
Restore a backup.

**Request (JSON):**
```json
{
  "backup": "job-uuid-20251122-143022.tar.gz"
}
```
(If `backup` is omitted, rolls back to the latest.)

**Response:**
```json
{
  "ok": true,
  "output": "restored job-uuid-20251122-143022.tar.gz"
}
```

#### `POST /api/service/restart`
Restart a systemd service.

**Request (JSON):**
```json
{
  "service": "openhab.service"
}
```

**Response:**
```json
{
  "ok": true,
  "output": "(systemctl output)"
}
```

#### `GET /api/status`
Health check (no auth required).

**Response:**
```json
{
  "jobs_total": 10,
  "jobs_running": 0
}
```

---

## File Structure

```
/opt/knx_to_openhab/                    # Application files
├── knxproject_to_openhab.py            # KNX parser (unchanged)
├── ets_to_openhab.py                   # OpenHAB generator (unchanged)
├── config.py                           # Config loader (unchanged)
├── config.json                         # Packaged generator defaults
├── requirements.txt                    # Python dependencies
├── web_ui/
│   ├── backend/
│   │   ├── app.py                      # Flask application & routes
│   │   ├── jobs.py                     # Job engine & backup logic
│   │   ├── storage.py                  # Config & jobs persistence
│   │   ├── service_manager.py          # systemctl wrapper
│   │   └── config.json                 # Local development defaults
│   ├── templates/
│   │   └── index.html                  # Web interface
│   ├── static/
│   │   ├── app.js                      # Frontend logic & SSE
│   │   └── style.css                   # Styling
│   └── README.md                       # Web UI
├── installer/
│   ├── setup.sh                        # Installation script
│   ├── backup_cleanup.sh               # Cleanup script
│   ├── knxohui.service                 # systemd unit (Flask)
│   ├── knxohui-backup-cleanup.service  # systemd unit (cleanup)
│   └── knxohui-backup-cleanup.timer    # systemd timer (daily)
├── openhab/                            # OpenHAB output folder (backed up before each job)
│   ├── items/
│   ├── things/
│   ├── sitemaps/
│   ├── persistence/
│   ├── rules/
│   └── icons/
└── venv/                               # Python virtual environment

/etc/knx_to_openhab/                    # Persistent configuration and secrets
├── config.json                         # Web UI runtime settings
├── secrets.env                         # Protected credentials
└── paths.env                           # Canonical installation paths

/var/lib/knx_to_openhab/                # Runtime data, outside the application
├── generator.json                      # User-controlled generator rules
├── jobs/                               # Job history and uploaded KNX files
├── staging/                            # Generated files awaiting deployment
└── generated/                          # Runtime-generated reports

/var/backups/knx_to_openhab/            # Backup archives
└── <job-id>-<timestamp>.tar.gz         # Backup tarballs
```

---

## Troubleshooting

### Web UI Not Accessible
```bash
# Check service is running
sudo systemctl status knxohui.service

# Check port 8085 is open
netstat -tulpn | grep 8085

# View service logs
sudo journalctl -u knxohui.service -n 50 -f

# Manually restart
sudo systemctl restart knxohui.service
```

### Permission Denied Errors

Deploy writes only the exact files configured for KNX generation. The installer
removes group and other write access under the effective OpenHAB configuration
root, reassigns service-owned non-output files to root, and provisions the
generated files for `knxohui`. File contents remain intact and manually
maintained files cannot be overwritten by deployment.

If a deploy reports that a managed output is missing or not writable, run the
administrator repair script:

```bash
sudo bash /opt/knx_to_openhab/fix_permissions.sh
```

After changing generator output paths, run `setup.sh` once so the new exact
output files are provisioned. Do not restore broad permissions with
`chmod -R 775 /etc/openhab`.

### Update Fails with "Permission denied"
If the update log shows "Permission denied" or "error: cannot open .git/FETCH_HEAD":

```bash
# Re-apply the managed file permissions and service policy
sudo bash /opt/knx_to_openhab/fix_permissions.sh
```

This can happen if installation files or the external backup directory were
changed by hand. The repair script reapplies the configured path and permission
policy; do not recursively change ownership of `/etc/openhab`.

### Backup/Rollback Issues
```bash
# Check the configured backup folder
sudo cat /etc/knx_to_openhab/paths.env
ls -lh /var/backups/knx_to_openhab

# Manual cleanup (if timer not working)
sudo systemctl start knxohui-backup-cleanup.service

# View cleanup logs
sudo journalctl -u knxohui-backup-cleanup.service
```

### Authentication Problems
```bash
# Check the external secret file permissions
sudo stat -c '%a %U:%G %n' /etc/knx_to_openhab/secrets.env

# Restart to apply
sudo systemctl restart knxohui.service
```

### Job Processing Stuck
```bash
# Kill stuck jobs
pkill -f "knxproject_to_openhab.py" || true

# Check job logs
tail -100 /var/lib/knx_to_openhab/jobs/jobs.json | python3 -m json.tool
```

---

## Advanced

### Disable Authentication
Edit `/etc/knx_to_openhab/config.json`:
```json
"auth": {
  "enabled": false
}
```

### Change Port
Edit `/etc/knx_to_openhab/config.json`:
```json
"port": 9000
```
Then restart: `sudo systemctl restart knxohui.service`

### Adjust Retention
Edit `/etc/knx_to_openhab/config.json`:
```json
"retention": {
  "days": 7,           // Keep 7 days instead of 14
  "max_backups": 100,  // Keep up to 100 backups
  "max_backups_size_mb": 1000  // Max 1GB total
}
```

### HTTPS and reverse proxy

Keep the application bound to `127.0.0.1` and terminate TLS in a local reverse
proxy. Set `trusted_proxy_hops` to the exact number of trusted proxies (usually
`1`) so Flask can recognize HTTPS from `X-Forwarded-Proto`. Do not accept
forwarded headers from clients that can reach Flask directly.

Example nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8085;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

When the proxy reports HTTPS, the session and CSRF cookies receive the `Secure`
attribute. Restrict access to the proxy and use TLS certificates appropriate for
your network.

---

## Logs and Debugging

### Application Logs
```bash
# Flask server logs
sudo journalctl -u knxohui.service -f

# Backup cleanup logs
sudo journalctl -u knxohui-backup-cleanup.service -f

# All KNX UI related
sudo journalctl -u knxohui.service -u knxohui-backup-cleanup.service -f
```

### Job Logs
View in the Web UI under "Job Details" > "Live Log"

Or access the JSON:
```bash
cat /var/lib/knx_to_openhab/jobs/jobs.json | python3 -m json.tool
```

---

## Security Notes

⚠️ **Network exposure**
- The default bind address is loopback, so other LAN devices cannot connect directly.
- Direct LAN access must be explicitly enabled and should be limited to a trusted network.
- Use HTTPS through a reverse proxy before allowing access over an untrusted network.

✅ **Best Practices**
1. Keep `/etc/knx_to_openhab/secrets.env` readable only by root and the service group
2. Use a strong, unique password
3. Keep `bind_host` on loopback behind a TLS reverse proxy for remote access
4. Restrict OpenHAB service restart via sudoers (already done in setup.sh)
5. Monitor `/var/lib/knx_to_openhab/` and `/var/backups/` for disk usage

---

## Support & Contributing

For issues or feature requests:
1. Check the API reference above
2. Review troubleshooting section
3. Check systemd logs: `sudo journalctl -u knxohui.service`
4. Open an issue on GitHub with logs and error messages

---

**Version:** 1.0  
**Last Updated:** 2025-11-22  
**License:** Same as knx_to_openhab project

