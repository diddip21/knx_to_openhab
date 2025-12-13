# KNX to OpenHAB Web UI — Installer Scripts

This directory contains installation and maintenance scripts for the web UI.

## Files

- **`setup.sh`** — Main installer script (run once as sudo)
- **`backup_cleanup.sh`** — Backup retention enforcement script
- **`knxohui.service`** — systemd unit for Flask web server
- **`knxohui-backup-cleanup.service`** — systemd unit for cleanup oneshot
- **`knxohui-backup-cleanup.timer`** — systemd timer (runs cleanup daily)

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

> **Note:** For local development without systemd installation, see [DEVELOPMENT.md](../DEVELOPMENT.md)

## Manual Service Control

```bash
# Start/stop web UI
sudo systemctl start knxohui.service
sudo systemctl stop knxohui.service
sudo systemctl restart knxohui.service

# Check status
sudo systemctl status knxohui.service

# View logs
sudo journalctl -u knxohui.service -f

# Run backup cleanup manually
sudo systemctl start knxohui-backup-cleanup.service

# Check timer status
sudo systemctl status knxohui-backup-cleanup.timer
```

## Uninstall

```bash
# Stop and disable services
sudo systemctl stop knxohui.service
sudo systemctl disable knxohui.service
sudo systemctl stop knxohui-backup-cleanup.timer
sudo systemctl disable knxohui-backup-cleanup.timer

# Remove service files
sudo rm /etc/systemd/system/knxohui.service
sudo rm /etc/systemd/system/knxohui-backup-cleanup.service
sudo rm /etc/systemd/system/knxohui-backup-cleanup.timer
sudo systemctl daemon-reload

# Remove installation
sudo rm -rf /opt/knx_to_openhab
sudo rm -rf /var/lib/knx_to_openhab
sudo rm -rf /var/backups/knx_to_openhab

# Remove sudoers entry
sudo rm /etc/sudoers.d/knxohui

# Remove system user
sudo userdel knxohui
```
