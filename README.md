# KNX to OpenHAB Generator

Generate complete OpenHAB configurations (Things, Items, Sitemaps) directly from your ETS project export (`.knxproj` / `.knxprojarchive`) or a JSON dump.

This project ships with a **Web UI** for guided uploads/configuration and a **CLI** for headless/automated use.

> **Status:** Current releases are intended for pilot / test deployments.

---

## System Requirements

- **OS (Installer):** Debian-based Linux (DietPi, Raspberry Pi OS, Ubuntu)
- **User:** Non‑root user with `sudo` privileges
- **Packages (installed by installer):** `git`, `python3`, `python3-venv`, `python3-pip`, `rsync`, `curl`
- **Supported ETS exports:** `.knxproj`, `.knxprojarchive`, `.json` dump
- **OpenHAB:** Any recent 3.x / 4.x install for deployment (generator outputs standard files)

---

## Recommended Quick Start (Web UI)

**Happy path, no method mix:** use the installer + UI.

### 1) Install

```bash
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/install.sh | bash
```

The installer will:
- clone to `/opt/knx_to_openhab`
- set up the `knxohui` systemd service
- configure permissions for self‑updates

### 2) Open the UI

Open your browser:
```
http://<your-ip>:8085
```
Default credentials:
- **User:** `admin`
- **Password:** `logihome` *(change this right away)*

To change credentials:
```
/opt/knx_to_openhab/web_ui/backend/config.json
```
Then:
```bash
sudo systemctl restart knxohui.service
```

### 3) Upload & Generate

1. Upload your `.knxproj` / `.knxprojarchive` (or `.json` dump)
2. Review floors/rooms and fix naming if needed
3. Generate OpenHAB files

### 4) Deploy Output

Generated files are written to:
```
/opt/knx_to_openhab/openhab/
```

If your OpenHAB config is elsewhere, set `openhab_path` in `config.json` (e.g. `/etc/openhab`).

---

## Updates & Uninstall

### Update

- **Via UI:** click the **Version** badge in the header
- **Via script:**
  ```bash
  curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/update.sh | bash
  ```

### Uninstall

```bash
curl -sSL https://raw.githubusercontent.com/diddip21/knx_to_openhab/main/uninstall.sh | bash
```

---

## CLI (Alternative)

```bash
python3 knxproject_to_openhab.py --file_path "MyHouse.knxproj"
```

Parameters:
- `--file_path`: path to `.knxproj` / `.knxprojarchive` or `.json` dump
- `--knxPW`: password for protected project files
- `--readDump`: read from JSON dump

---

## Known Limitations (Current)

- Some DPTs or device profiles may not be fully mapped yet.
- Dimmer / rollershutter detection relies on ETS naming conventions.
- Auto‑placement is optional and may create generic floor/room structure.
- Web UI is intended for LAN use (basic auth, no HTTPS by default).

---

## More Documentation

- **[User Guide](docs/USER_GUIDE.md)** — configuration, ETS prep, troubleshooting
- **[Production Guide](docs/PRODUCTION_GUIDE.md)** — Raspberry Pi / DietPi setup, services
- **[Developer Guide](docs/DEVELOPER_GUIDE.md)** — architecture, testing, local dev

---

## License

This project is open-source.
