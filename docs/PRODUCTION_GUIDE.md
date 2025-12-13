# Production Installation Guide — KNX to OpenHAB

## Overview

A lightweight, browser-based web interface to execute the KNX-to-OpenHAB generator on a Raspberry Pi (DietPi) without Docker. Includes real-time progress streaming, automatic backups, rollback capability, retention policies, and basic HTTP authentication.

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
✅ **Basic HTTP Auth** — Simple username/password protection (configurable)  
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
3.  Setup the service user and permissions
4.  Install/Update systemd services
5.  Print the access URL and credentials

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

### Step 3: Change Default Credentials

Edit `/opt/knx_to_openhab/web_ui/backend/config.json`:

```bash
sudo nano /opt/knx_to_openhab/web_ui/backend/config.json
```

Change:
```json
"auth": {
  "enabled": true,
  "user": "YOUR_USERNAME",
  "password": "YOUR_STRONG_PASSWORD"
}
```

Then restart the service:
```bash
sudo systemctl restart knxohui.service
```

### Uninstallation
To completely remove the application, use the uninstaller script:
```bash
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash
```
This will stop services, remove the installation directory, remove the service user, and clean up logs/backups.

---

## Usage

### Access the Web UI

Open in your browser:
```
http://<pi-ip-address>:8085
```

You will be prompted for username/password (default: `admin` / `logihome`).

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
4. **Confirm** — the `openhab/` folder is restored

### Restart OpenHAB

1. **Go to "Services"** section at the bottom
2. **Click "Restart OpenHAB"** button
3. **Wait for confirmation** — shows if restart was successful

---

## Configuration

### Main Config File
Location: `/opt/knx_to_openhab/web_ui/backend/config.json`

```json
{
  "openhab_path": "openhab",                    // Where OpenHAB files are (relative to base)
  "jobs_dir": "var/lib/knx_to_openhab",         // Job history + uploads
  "backups_dir": "var/backups/knx_to_openhab",  // Backup tar.gz files
  "bind_host": "0.0.0.0",                        // Listen address (0.0.0.0 = all interfaces)
  "port": 8085,                                  // Web server port
  "auth": {
    "enabled": true,                             // Set to false to disable auth
    "user": "admin",                             // Basic HTTP username
    "password": "logihome"                       // Basic HTTP password
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

All endpoints require HTTP Basic Auth unless `auth.enabled` is `false`.

#### `POST /api/upload`
Upload a KNX project file.

**Request:**
```
Content-Type: multipart/form-data
Authorization: Basic base64(user:password)
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
/opt/knx_to_openhab/                    # Installation base
├── knxproject_to_openhab.py            # KNX parser (unchanged)
├── ets_to_openhab.py                   # OpenHAB generator (unchanged)
├── config.py                           # Config loader (unchanged)
├── config.json                         # Main config (unchanged)
├── requirements.txt                    # Python dependencies
├── web_ui/
│   ├── backend/
│   │   ├── app.py                      # Flask application & routes
│   │   ├── jobs.py                     # Job engine & backup logic
│   │   ├── storage.py                  # Config & jobs persistence
│   │   ├── service_manager.py          # systemctl wrapper
│   │   └── config.json                 # Web UI config
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

/var/lib/knx_to_openhab/                # Runtime data
├── jobs.json                           # Job history
└── <job-uploads>/                      # Uploaded KNX files (by job ID)

/var/backups/knx_to_openhab/            # Backup archives
└── <job-id>-<timestamp>.tar.gz         # Backup tarballs
```

---

## Troubleshooting

### Web UI Not Accessible
```bash
# Check service is running
sudo systemctl status knxohui.service

# Check port 8080 is open
netstat -tulpn | grep 8080

# View service logs
sudo journalctl -u knxohui.service -n 50 -f

# Manually restart
sudo systemctl restart knxohui.service
```

### Update Fails with "Permission denied"
If the update log shows "Permission denied" or "error: cannot open .git/FETCH_HEAD":

```bash
# Fix ownership permissions
sudo chown -R knxohui:knxohui /opt/knx_to_openhab /var/backups/knx_to_openhab
```

This usually happens if you manually ran git commands as root or your personal user instead of the service user.

### Backup/Rollback Issues
```bash
# Check backup folder
ls -lh /var/backups/knx_to_openhab/

# Manual cleanup (if timer not working)
sudo systemctl start knxohui-backup-cleanup.service

# View cleanup logs
sudo journalctl -u knxohui-backup-cleanup.service
```

### Authentication Problems
```bash
# Change credentials in config
sudo nano /opt/knx_to_openhab/web_ui/backend/config.json

# Restart to apply
sudo systemctl restart knxohui.service
```

### Job Processing Stuck
```bash
# Kill stuck jobs
pkill -f "knxproject_to_openhab.py" || true

# Check job logs
tail -100 /var/lib/knx_to_openhab/jobs.json | python3 -m json.tool
```

---

## Advanced

### Disable Authentication
Edit `/opt/knx_to_openhab/web_ui/backend/config.json`:
```json
"auth": {
  "enabled": false
}
```

### Change Port
Edit `/opt/knx_to_openhab/web_ui/backend/config.json`:
```json
"port": 9000
```
Then restart: `sudo systemctl restart knxohui.service`

### Adjust Retention
Edit `/opt/knx_to_openhab/web_ui/backend/config.json`:
```json
"retention": {
  "days": 7,           // Keep 7 days instead of 14
  "max_backups": 100,  // Keep up to 100 backups
  "max_backups_size_mb": 1000  // Max 1GB total
}
```

### HTTPS Setup
For production, add a reverse proxy (nginx) or use Let's Encrypt. Currently HTTP-only, suitable for local LAN.

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
cat /var/lib/knx_to_openhab/jobs.json | python3 -m json.tool
```

---

## Security Notes

⚠️ **For Local LAN Use Only**
- Basic HTTP auth is simple (not encrypted, only base64)
- No HTTPS by default
- Suitable for trusted local networks only
- Do not expose to the internet without additional security (reverse proxy + SSL)

✅ **Best Practices**
1. Change default credentials immediately
2. Use a strong password
3. If exposing remotely, add nginx reverse proxy with SSL
4. Restrict OpenHAB service restart via sudoers (already done in setup.sh)
5. Monitor `/var/lib/knx_to_openhab/` and `/var/backups/` for disk usage

---

## Support & Contributing

For issues or feature requests:
1. Check the API reference above
2. Review troubleshooting section
3. Check systemd logs: `sudo journalctl -u knxohui.service`
  sudo systemctl start knxohui-backup-cleanup.service
4. Open an issue on GitHub with logs and error messages

---

**Version:** 1.0  
**Last Updated:** 2025-11-22  
**License:** Same as knx_to_openhab project

