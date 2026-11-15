# KNX to OpenHAB Web UI — Installer Scripts

This directory contains installation and maintenance scripts for the web UI.

## Files

- **`setup.sh`** — Main installer script (run once as sudo)
- **`backup_cleanup.sh`** — Backup retention enforcement script
- **`knxohui.service`** — systemd unit for Flask web server
- **`knxohui-update.service`** — independent systemd unit for release updates
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
4. Install systemd launchers, the update worker, and the backup-cleanup timer
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
Argon2id hashes in the restricted secrets file. If no usable password exists, setup
generates a random password, stores only its hash, and prints the new password once. This
also replaces the old shared default and lets setup recover after a partially completed
migration without an interactive prompt. Save that output before continuing; the password
is not written to a plaintext file. Use the password helper below to set a different
password later. Runtime settings remain in `config.json`.

The Web UI and generator both read the saved path environment, so the Settings
screen writes `/var/lib/knx_to_openhab/generator.json` and future releases do not
need to carry user configuration or job data. To inspect the active paths:

```bash
sudo cat /etc/knx_to_openhab/paths.env
sudo ls -la /etc/knx_to_openhab /var/lib/knx_to_openhab /var/backups/knx_to_openhab
```

### Login behind a relay that drops the CSRF cookie

The relay should normally pass `Set-Cookie` and `Cookie` headers unchanged.
If it drops only the login CSRF cookie, an administrator can add this setting to
the existing Web UI settings object at `/etc/knx_to_openhab/config.json`,
preserving its other settings:

```json
{
  "login_csrf_allowed_origins": ["https://mcrelay.greiner-wue.de"]
}
```

Use an exact origin (scheme, host, and optional port), with no path. This
fallback keeps the signed, time-limited login token and requires an exact
`Origin` match (or `Referer` when `Origin` is absent); it does not disable
authentication or CSRF protection. The relay must still pass the
post-login `knx_session` and `knx_csrf` cookies, or sign-in cannot persist.
After changing the setting, restart the Web UI service so it reloads the config:

```bash
sudo systemctl restart knxohui.service
```

#### When the relay strips all cookies

If the relay cannot pass `Cookie`/`Set-Cookie`, opt in to HTTP Basic
authentication in the same config file by adding these fields inside the
existing `auth` object (preserve its other fields):

```json
"auth": {
  "enabled": true,
  "mode": "basic",
  "allowed_origins": ["https://mcrelay.greiner-wue.de"]
}
```

Basic mode checks the configured Web UI username/password on each request and
does not use session cookies. The relay must pass the `Authorization` header;
if it strips that too, this mode cannot work. The public connection must use
HTTPS, and the relay-to-app hop carrying the Basic credentials must be loopback,
TLS-protected, or on a network you trust. Do not expose the app directly over
unencrypted HTTP. If the relay runs on the same host, keep `bind_host` at
`127.0.0.1`; if it is remote, protect the upstream hop with TLS. For
state-changing requests the app still requires an exact HTTPS allowed `Origin`
(or `Referer` only when `Origin` is absent). The existing rate limit still
applies. Browsers may cache Basic credentials until closed, so the
in-app logout button is unavailable and closing the browser is the practical
way to clear them. Restart `knxohui.service` after changing the configuration.

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

The web UI runs as the unprivileged `knxohui` service user. Application updates
are queued by that user and run in the separate `knxohui-update.service`, so a
restart of the web service cannot kill the updater before its health check or
rollback completes. Git is not granted through sudo. The sudoers policy in
`knxohui.sudoers` permits only exact `systemctl restart` and `systemctl is-active`
commands for `openhab.service`, `knxohui.service`, and `evcc.service`. It does not
grant a shell, arbitrary Git commands, or wildcard command arguments. Re-running
`setup.sh` or `fix_permissions.sh` replaces the prior policy and checks it with
`visudo -cf`.

The update worker is started only through the fixed `start-web-update` action of
the root-owned `/usr/local/sbin/knxohui-service-update` helper. Package update
buttons use the same helper. Sudoers allows only its `start-web-update`, `refresh`,
`openhab`, `evcc`, and `provision-yaml` actions. The YAML action runs a separate
root-owned helper that provisions only the
configured `.yaml` target directly under the protected OpenHAB `yaml/` directory;
it does not import or execute code from the application tree. The installer preserves
an existing `web_ui/backend/config.json` when copying new code and records the
resolved OpenHAB root in protected configuration for that helper.

### Top-level installer modes

The root `install.sh` now distinguishes first installation from actions on an
existing installation:

| Command | Behavior |
|---------|----------|
| `bash install.sh --install` | Install the latest stable release when the target directory does not exist |
| `bash install.sh --update` | Update an existing Git checkout to the latest stable release, then run setup |
| `bash install.sh --repair` | Run setup for an existing installation without fetching a release |
| `bash install.sh --cancel` | Exit before requesting sudo or installing packages |

Use `--version X.Y.Z` with `--install` or `--update` to select an exact
published release. The version omits the `v` tag prefix. Explicit SemVer
prereleases such as `1.3.0-rc.1` can be selected this way; they are never
chosen by the default stable channel. If GitHub has no matching release, the
installer stops instead of falling back to `main`.

Before requesting sudo, the entry point checks for Python 3.11 or newer and at
least 1 GiB of free space on the installation filesystem. `--install` and
`--update` resolve the selected GitHub release before installing packages, so
an unavailable release or network fails before package changes. After system
packages are available, a temporary Python virtual environment is created and
removed to verify venv support before cloning or running setup. `--repair`
does not fetch a release, but its dependency and setup steps may still need
network access. When all required system packages are installed, a repeated
run skips `apt-get update`; Python package installation in setup may still
access a package index. `--help` and `--cancel` work without Python.
Before setup creates or reuses the `knxohui` service account, it checks that
an existing account uses the matching primary group and a non-login shell.
Incompatible accounts stop setup before services or file ownership change.
When setup fails, the top-level installer returns its exit code to the caller.

On a first install, running without a mode keeps `--install` as the default.
For an existing installation, an interactive run asks for update, repair, or
cancel; a non-interactive run stops with an explicit instruction instead of
changing the system. An existing directory is never overwritten by
`--install`. These choices make the entry point safer; they do not yet make
every operation in `setup.sh` idempotent or add a reinstall flow (Issue #25
remains open for those items).

The top-level installer resolves the GitHub release and checks out its exact
tag. It does not yet stage a separate release directory or verify the published
archive checksum before activation; the transactional updater work in Issue #26
owns those guarantees.

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

Run the repository's uninstaller as a regular user with `sudo` available. It
lists the affected services and paths before asking for confirmation:

```bash
bash /opt/knx_to_openhab/uninstall.sh
```

The normal uninstall stops and disables the KNX to openHAB services and removes
the application, systemd units, sudoers entry, and root-owned launch/update
helpers. It preserves the configured directories for configuration, runtime
data and backups, along with the `knxohui` service account and group. The
configured paths are read from `/etc/knx_to_openhab/paths.env` as data, never
executed as shell code. The uninstaller rejects unsafe, overlapping, broad, or
symlinked paths. If legacy jobs or backups still sit inside the application
tree, it stops before changing anything so the current setup migration can
move them safely first.

For a full removal, run the explicit purge mode. Type `PURGE` at its prompt:

```bash
bash /opt/knx_to_openhab/uninstall.sh --purge
```

For non-interactive automation, use `--purge --yes`. A regular non-interactive
uninstall likewise requires `--yes`. The purge also removes the configured
configuration, runtime and backup directories, plus the service account and
group. It previews those extra targets separately before proceeding.

The script is safe to run again after an uninstall; when the application,
service integration and path registry are already absent, it exits without
touching the fallback paths.

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
