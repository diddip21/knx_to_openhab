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

### Existing installations

The old policy allowed the service user to run arbitrary Git commands as root.
The Web UI cannot safely use that old permission to replace its own sudoers file.
Do not use the Web UI updater for the first transition. After this change has
been merged, an administrator should pull the source as the service user and
then install the new policy:

```bash
sudo -u knxohui git -C /opt/knx_to_openhab pull --ff-only origin main
sudo bash /opt/knx_to_openhab/installer/migrate_sudoers.sh
```

The migration only replaces `/etc/sudoers.d/knxohui` and validates the resulting
policy; it does not copy
application files or modify configuration and job data. The new updater stops
and prints the migration command while the old Git wildcard policy remains.

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
