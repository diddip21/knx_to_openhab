# KNX to OpenHAB Web UI — Installer Scripts

This directory contains installation and maintenance scripts for the web UI.

## Files

- **`setup.sh`** — Main installer script (run once as sudo)
- **`backup_cleanup.sh`** — Backup retention enforcement script
- **`knxui.service`** — systemd unit for Flask web server
- **`knxui-backup-cleanup.service`** — systemd unit for cleanup oneshot
- **`knxui-backup-cleanup.timer`** — systemd timer (runs cleanup daily)

## Quick Install

```bash
chmod +x setup.sh backup_cleanup.sh
sudo ./setup.sh
```

This will:
1. Install the web UI to `/opt/knx_to_openhab`
2. Create system user and directories
3. Install systemd services and timer
4. Start the Flask web server on port 8080

See `WEBUI_INSTALLATION.md` for full documentation.

## Manual Service Control

```bash
# Start/stop web UI
sudo systemctl start knxui.service
sudo systemctl stop knxui.service
sudo systemctl restart knxui.service

# Check status
sudo systemctl status knxui.service

# View logs
sudo journalctl -u knxui.service -f

# Run backup cleanup manually
sudo systemctl start knxui-backup-cleanup.service

# Check timer status
sudo systemctl status knxui-backup-cleanup.timer
```

## Uninstall

```bash
# Stop and disable services
sudo systemctl stop knxui.service
sudo systemctl disable knxui.service
sudo systemctl stop knxui-backup-cleanup.timer
sudo systemctl disable knxui-backup-cleanup.timer

# Remove service files
sudo rm /etc/systemd/system/knxui.service
sudo rm /etc/systemd/system/knxui-backup-cleanup.service
sudo rm /etc/systemd/system/knxui-backup-cleanup.timer
sudo systemctl daemon-reload

# Remove installation
sudo rm -rf /opt/knx_to_openhab
sudo rm -rf /var/lib/knx_to_openhab
sudo rm -rf /var/backups/knx_to_openhab

# Remove sudoers entry
sudo rm /etc/sudoers.d/knxui

# Remove system user
sudo userdel knxui
```

## Development

To run locally without installing:

```bash
# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install deps
pip install -r ../requirements.txt

# Run Flask dev server
cd ..
PYTHONPATH=. .venv/bin/python -m flask --app web_ui.backend.app:app run
```

Then open `http://localhost:5000` in your browser.

