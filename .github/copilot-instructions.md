# Copilot instructions for knx_to_openhab

Follow [AGENTS.md](../AGENTS.md) for the current architecture, coding rules, tests, and review requirements. This file exists for GitHub Copilot discovery and does not maintain a second copy of those instructions.

The CLI entry is knxproject_to_openhab.py; the generator and output writer are in ets_to_openhab.py. YAML rendering is in openhab_yaml.py. The Web UI starts in web_ui/backend/app.py and processes jobs in web_ui/backend/jobs.py.

Run the Linux core test command documented in AGENTS.md and the UI command separately. Keep legacy and YAML output behavior stable, and verify changes against all three golden projects.
