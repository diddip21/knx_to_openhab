# Copilot instructions for knx_to_openhab

Use [`AGENTS.md`](../AGENTS.md) as the maintained source for architecture, coding conventions, testing commands, compatibility rules and known pitfalls. Consult [`docs/DEVELOPER_GUIDE.md`](../docs/DEVELOPER_GUIDE.md) for integrated runtime paths, installer behavior and release gates. Avoid copying line counts or endpoint lists into this file; they change as the project evolves.

## Before changing code

- Trace the affected path from KNX input through `knxproject_to_openhab.py`, `ets_to_openhab.py`, staging in `web_ui/backend/jobs.py` and the generated output. `config.py` executes on import; the generator has mutable module state.
- Preserve existing defaults and configuration keys. Optional YAML output must not silently replace legacy output. Save sibling settings intact.
- Check authorization and CSRF in `web_ui/backend/app.py` for new routes. Constrain deployment and rollback through `web_ui/backend/deploy_policy.py`; never widen write access to all of `/etc/openhab` or expose arbitrary root commands.
- Treat migration of existing installations as a separate release gate. Use only isolated copies for setup, package-update or rollback rehearsals; automated tests alone do not approve a productive upgrade.

## Verification

Run `black --check .`, `isort --check-only .`, `flake8 .`, `mypy .` and `pytest -q -m "not ui" --ignore=tests/ui`. For UI changes, run `pytest tests/ui/ -v -m ui --tb=short` with Chromium installed; CI runs the same browser suite. For generator changes, review and regenerate golden fixtures with `python scripts/regenerate_golden.py`, then inspect their diff. Record unavailable checks and real-device limitations explicitly.
