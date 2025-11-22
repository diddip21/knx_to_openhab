KNX → OpenHAB Web UI

Lightweight Flask web interface for `knxproject_to_openhab.py`.

Install (on DietPi / Raspberry Pi, without Docker):

```bash
sudo ./installer/setup.sh
```

Default server: `http://<pi-ip>:8080`

API endpoints (JSON): see `api_schema.json`.

Backups are stored under `/var/backups/knx_to_openhab` and jobs metadata under `/var/lib/knx_to_openhab`.
