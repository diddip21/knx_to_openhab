# KNX to OpenHAB Web UI — Installer Scripts

This directory contains installation and maintenance scripts for the web UI.

## Versioned release artifacts

`VERSION` is the single semantic-version source. Maintainers publish a release
by creating and pushing a matching `v<VERSION>` Git tag. The release workflow
builds `knx_to_openhab-<VERSION>.tar.gz` and its `.sha256` sidecar from tracked
application source; tests, generated OpenHAB output, runtime data, local
secrets, and ETS project files are excluded. The checksum must be verified by
installers and updaters before extracting or activating an artifact.

Prerelease tags such as `v0.2.0-beta.1` and `v0.2.0-rc.1` are published as
GitHub prereleases. Stable releases remain the default channel; selecting a
prerelease is an explicit installer/updater choice. Creating or pushing a tag
is a maintainer action and is not performed by the build script.

## Files

- **`setup.sh`** — Privileged setup implementation called by the verified bootstrap; do not run it directly
- **`backup_cleanup.sh`** — Backup retention enforcement script
- **`knxohui.service`** — systemd unit for Flask web server
- **`knxohui-backup-cleanup.service`** — systemd unit for cleanup oneshot
- **`knxohui-backup-cleanup.timer`** — systemd timer (runs cleanup daily)

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash
```

The installer must run as a regular user with `sudo` access. It selects the
latest stable GitHub release by default, downloads the source archive and its
SHA-256 sidecar, verifies the checksum, validates archive paths, then stages
the immutable release before changing `current`. Git is not used to install or
update application code.

For an explicit prerelease install, download the bootstrap script and select
the prerelease channel:

```bash
curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh \
  -o /tmp/knxoh-install.sh
bash /tmp/knxoh-install.sh --channel prerelease
```

When an installation already exists, the installer offers **Update**,
**Repair**, **Reinstall**, and **Cancel**. In non-interactive use, choose one
explicitly (`--update`, `--repair`, `--reinstall`, or `--cancel`) or use
`--plan` to inspect the action without making changes. Repair restores missing
system components only; it does not migrate, overwrite, or delete configuration,
secrets, jobs, runtime data, or backups. Update and reinstall preserve those
external paths while installing a new release. Release directories are
root-owned and not writable by the service account. If the selected version is
already active, reinstall performs a system-component repair instead of
replacing its files. The bootstrap refuses to run privileged repair code from a
release tree the service account can modify.

`setup.sh` is called by the verified bootstrap installer. Run repairs through
the bootstrap as a regular user with `sudo` access; do not run a release-owned
setup script directly as root:

```bash
curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh \
  -o /tmp/knxoh-install.sh
bash /tmp/knxoh-install.sh --repair
```

Legacy flat installations cannot be safely repaired in place because their
application files may be writable by the service account. Choose `--update` to
migrate them into a verified immutable release; external settings and runtime
data remain in their existing paths.

The normal setup process will:
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

If setup is interrupted after a release directory is prepared but before
`current` is switched, the release carries a `.install-incomplete` marker.
Choosing Repair validates the release, restores missing system integration,
atomically activates it, and removes the marker after successful service setup.
Incomplete hidden staging directories are discarded only inside
`releases/`; external user data is never part of that cleanup.

### Runtime paths and migration

| Data | Default location |
|------|------------------|
| Application code | `/opt/knx_to_openhab/current` (versions under `releases/<version>`) |
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
sudo /opt/knx_to_openhab/current/venv/bin/python \
  /usr/local/libexec/knx_to_openhab/set_ui_password.py
sudo systemctl restart knxohui.service
```

The root-owned helper hashes the new password with Argon2id, resolves the
configured secrets path from `paths.env`, preserves other secret values, and
does not put the password in shell history.

See `WEBUI_INSTALLATION.md` for full documentation.

## Service user privileges

The web UI runs as the unprivileged `knxohui` service user. The installer
downloads and verifies release artifacts; Git is not granted through sudo. The sudoers policy in
`knxohui.sudoers` permits only exact `systemctl restart` and `systemctl is-active`
commands for `openhab.service`, `knxohui.service`, and `evcc.service`. It does not
grant a shell, arbitrary Git commands, or wildcard command arguments. Each
verified-bootstrap install or repair replaces the prior policy and checks it
with `visudo -cf`; do not invoke `setup.sh` directly.

The package update buttons use the root-owned `/usr/local/sbin/knxohui-service-update`
helper. Sudoers allows only its `refresh`, `openhab`, and `evcc` actions. The
installer keeps Web UI settings, secrets, jobs, and backups in canonical external paths.

### Existing installations

The old policy allowed the service user to run arbitrary Git commands as root.
The Web UI cannot safely use that old permission to replace its own sudoers file.
An administrator can run the release-aware installer once to apply the current
stable release and install the restricted service policy:

```bash
curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh \
  -o /tmp/knxoh-install.sh
bash /tmp/knxoh-install.sh --update
```

The installer preserves external runtime configuration while installing missing
system components and applying the restricted sudoers policy. Run this migration
through the release-aware bootstrap even when no application update is otherwise
needed; do not invoke a release-owned migration script directly as root.

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

Download and run the uninstaller as a regular user with `sudo` access:

```bash
curl -fsSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh \
  -o /tmp/knxohui-uninstall.sh
bash /tmp/knxohui-uninstall.sh
```

The default mode lists its actions, asks you to type `UNINSTALL`, and removes
application releases and service files only. Configuration (`/etc/knx_to_openhab`),
jobs/runtime data (`/var/lib/knx_to_openhab`), backups
(`/var/backups/knx_to_openhab`), and the `knxohui` service account are retained.
The paths recorded in `/etc/knx_to_openhab/paths.env` are used when they differ
from these defaults.

To also delete configuration, jobs, backups, and the service account, explicitly
request purge. The uninstaller asks for both `UNINSTALL` and `PURGE` before it
does anything:

```bash
bash /tmp/knxohui-uninstall.sh --purge
```

Do not use `--purge` unless those user data directories should be permanently erased.

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
Changing configured output paths requires explicit permission provisioning; do
not rerun the privileged `setup.sh` directly. The Web UI updater does not change
system file permissions.
