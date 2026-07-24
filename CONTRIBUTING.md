# Contributing to knx_to_openhab

Thanks for your interest in contributing! This guide covers the basics.

## Development Setup

```bash
git clone https://github.com/diddip21/knx_to_openhab.git
cd knx_to_openhab
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Start dev server
flask --app web_ui.backend.app:app run --debug
```

See [Developer Guide](docs/DEVELOPER_GUIDE.md) for full details.

## Branch Naming

| Prefix | Use case |
|--------|----------|
| `feature/` | New features |
| `fix/` or `issue-` | Bug fixes (reference issue number) |
| `docs/` | Documentation changes |
| `chore/` | Maintenance, refactoring |

Examples: `feature/new-dpt-mapping`, `fix/issue-6-update-path`, `docs/issue-8-readme`

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add DPT 21.001 mapping for window state
fix: pass INSTALL_DIR to update.sh for non-default paths
docs: improve README quickstart section
chore: remove unused imports
style: apply black formatting
test: add Web UI update endpoint tests
```

## Code Style

This project enforces:

- **Black** (line-length 100) — auto-formatter
- **isort** (profile=black) — import sorting
- **flake8** (max-line-length 100) — linting

Run before committing:

```bash
black .
isort .
flake8 .
```

Or all at once:

```bash
black . && isort . && flake8 .
```

## Pull Request Checklist

Before opening a PR:

- [ ] Code passes `black --check .`
- [ ] Code passes `isort --check-only .`
- [ ] Code passes `flake8 .`
- [ ] All tests pass: `pytest -q`
- [ ] New tests added (if applicable)
- [ ] Golden files regenerated (if output logic changed): `python scripts/regenerate_golden.py`
- [ ] Documentation updated (if needed)
- [ ] Commit messages follow conventional format

## Running Tests

```bash
# Quick (core tests only)
pytest -q

# With coverage
pytest --cov=. --cov-report=html

# Specific group
pytest tests/integration -v
pytest -m unit

# UI tests (needs Playwright)
pip install pytest-playwright
python -m playwright install chromium
pytest tests/ui -v -o addopts=
```

See [tests/README.md](tests/README.md) for details.

## Project Structure

```
knxproject_to_openhab.py    # Entry: KNX parser
ets_to_openhab.py           # Core: OpenHAB generator
config.json                 # Detection rules, DPT mappings
config.py                   # Config loader (executes on import!)
completeness.py             # Post-generation validation
web_ui/backend/             # Flask API + job management
web_ui/static/              # Frontend (vanilla JS)
tests/                      # Unit, integration, UI tests
scripts/                    # Dev helpers (golden file regen, etc.)
```

## Key Pitfalls

- **`config.py` executes on import** — every `import config` triggers file I/O
- **`ets_to_openhab.py` uses global state** — reset in test `setup_method()`
- **`gen_building()` is 500+ lines** — understand the 3-pass logic before modifying
- **Golden files** — regenerate after any output change: `python scripts/regenerate_golden.py`

## Reporting Issues

Open an issue on [GitHub](https://github.com/diddip21/knx_to_openhab/issues) with:

- Description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Logs (if applicable): `sudo journalctl -u knxohui.service -n 50`
