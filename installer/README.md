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
# Run from the repository root.
sudo bash installer/setup.sh
```

This will:
1. Install the web UI to `/opt/knx_to_openhab`
2. Create system user and directories
3. Install systemd services and timer
4. Start the Flask web server on port 8080
5. Install and validate a restricted sudoers policy with `visudo`

See `WEBUI_INSTALLATION.md` for full documentation.

## Service user privileges

The web UI runs as the unprivileged `knxohui` service user. Git-based application
updates run as that user; Git is not granted through sudo. The sudoers policy in
`knxohui.sudoers` permits only exact `systemctl restart` and `systemctl is-active`
commands for `openhab.service`, `knxohui.service`, and `evcc.service`. It does not
grant a shell, arbitrary Git commands, or wildcard command arguments. Re-running
`setup.sh` or `fix_permissions.sh` replaces the prior policy and checks it with
`visudo -cf`.

The package update buttons use the root-owned `/usr/local/sbin/knxohui-service-update`
helper. Sudoers allows only its `refresh`, `openhab`, and `evcc` actions. The
installer preserves an existing `web_ui/backend/config.json` when copying new code.

### Existing installations

The old policy allowed the service user to run arbitrary Git commands as root.
The Web UI cannot safely use that old permission to replace its own sudoers file.
After the source update has been applied, an administrator must run the installer
once before using package updates or starting another Web UI update:

```bash
cd /opt/knx_to_openhab
sudo bash installer/setup.sh
```

The installer preserves the existing runtime configuration while installing the
root-owned package helper and its exact sudoers entries. It also replaces and
validates the old policy. If only the least-privilege migration is needed, use
`sudo bash installer/migrate_sudoers.sh`; that script changes only the sudoers
file.

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
