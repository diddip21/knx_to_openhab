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
1. Install the application under `/opt/knx_to_openhab` by default
2. Migrate settings and runtime data out of the application tree
3. Provision the service user and only the generated OpenHAB output files
4. Install systemd launchers and the backup-cleanup timer
5. Install and validate the restricted sudoers policy with `visudo`
6. Start the Flask web server on the configured port (8085 by default)

The installation directories can be selected with `KNXOH_INSTALL_DIR`,
`KNXOH_CONFIG_DIR`, `KNXOH_DATA_DIR`, and `KNXOH_BACKUP_DIR` before running
`setup.sh`. Existing values are saved in `/etc/knx_to_openhab/paths.env` and
reused on later setup runs. The paths must be absolute, separate, and outside
the application directory.

### Runtime paths and migration

| Data | Default location |
|------|------------------|
| Application code | `/opt/knx_to_openhab` |
| Web UI settings | `/etc/knx_to_openhab/config.json` |
| Generator rules | `/var/lib/knx_to_openhab/generator.json` |
| Web UI secrets | `/etc/knx_to_openhab/secrets.env` |
| Jobs and uploads | `/var/lib/knx_to_openhab/jobs/` |
| Staging output | `/var/lib/knx_to_openhab/staging/` |
| Generated runtime data | `/var/lib/knx_to_openhab/generated/` |
| Backup archives | `/var/backups/knx_to_openhab/` |

`setup.sh` copies existing settings, jobs, uploads, and backups before changing
the active paths. It checks for conflicting files and refuses symlinked or
system-wide legacy source directories. Only after a successful copy does it
remove legacy job or backup directories inside the application tree. The old
root `config.json` is copied to `generator.json` before the application tree is
reset to the packaged defaults. Existing user-chosen Web UI passwords are converted to
Argon2id hashes in the restricted secrets file. The shipped default password is discarded,
and setup prompts for a replacement. A fresh install also prompts for a unique password;
runtime settings remain in `config.json`.

The Web UI and generator both read the saved path environment, so the Settings
screen writes `/var/lib/knx_to_openhab/generator.json` and future releases do not
need to carry user configuration or job data. To inspect the active paths:

```bash
sudo cat /etc/knx_to_openhab/paths.env
sudo ls -la /etc/knx_to_openhab /var/lib/knx_to_openhab /var/backups/knx_to_openhab
```

### Change the Web UI password

The installer keeps the Web UI password in the protected `secrets.env` file.
To set or rotate it, run the helper, enter the new password twice, then restart
the service:

```bash
sudo /opt/knx_to_openhab/venv/bin/python \
  /usr/local/libexec/knx_to_openhab/set_ui_password.py
sudo systemctl restart knxohui.service
```

The root-owned helper hashes the new password with Argon2id, resolves the
configured secrets path from `paths.env`, preserves other secret values, and
does not put the password in shell history.

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
helper. Sudoers allows only its `refresh`, `openhab`, `evcc`, and `provision-yaml`
actions. The YAML action runs a separate root-owned helper that provisions only the
configured `.yaml` target directly under the protected OpenHAB `yaml/` directory;
it does not import or execute code from the application tree. The installer preserves
an existing `web_ui/backend/config.json` when copying new code and records the
resolved OpenHAB root in protected configuration for that helper.

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
root-owned package and YAML-provisioning helpers and their exact sudoers entries.
It also replaces and validates the old policy. If only the least-privilege
migration is needed, use `sudo bash installer/migrate_sudoers.sh`; that script
changes only the sudoers file.

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

Use the repository's `uninstall.sh` when the safe uninstall/purge workflow from
Issue #28 is available. Until that work lands, the manual commands below are
destructive: remove the configuration and backups only if you intend to erase
them permanently.

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

## OpenHAB output permissions

The installer keeps the `openhab` group for read access and removes group and
other write access under the effective OpenHAB configuration root. Objects
owned by `knxohui` outside the generated output allowlist are reassigned to
`root`; configured generated files are provisioned as `knxohui:openhab` with
mode `0640`. File contents are left intact. The same provisioning runs from
`fix_permissions.sh` when an administrator repairs an existing installation.

Deploy accepts only the configured generated outputs in their expected OpenHAB
directories. It rejects traversal, symlinks, and missing pre-provisioned files.
Backups still contain the full OpenHAB configuration tree, while rollback
restores only generator-managed files so manual configuration is preserved.
Re-run `setup.sh` after changing output paths so the new exact files can be
provisioned; the Web UI updater does not change system file permissions.
