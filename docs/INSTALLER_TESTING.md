# Installer and updater integration tests

The installer lifecycle harness runs on Linux and invokes the real top-level
`install.sh` against a temporary installation directory. It replaces GitHub
release lookup, `git clone`, `sudo`, `rsync`, and package inspection with local
stubs. The setup script in the fake release records each run and preserves a
user-data file so the test can verify a clean install, a refused second install,
and repair without contacting GitHub or replacing data. No host services or
system directories are modified.

The transactional updater integration tests use temporary directories, a local
HTTP health endpoint, and command stubs. They cover backup validation, no-op,
successful activation and release cleanup, activation failure, and health-check
rollback. Separate cases simulate release preparation/download and dependency
installation failures, and verify that the previous install and runtime data
remain intact. These tests require Bash and `flock`; they are skipped on Windows
and run in the Linux GitHub Actions core-test jobs.

Run the focused tests on Linux with:

```bash
pytest -q tests/test_installer_lifecycle.py tests/test_privilege_policy.py tests/test_update_backup.py
```

The Web UI update flow has a Playwright test that clicks the update action,
checks the POST request, and waits for the updater log. Run it with:

```bash
pytest -q tests/ui/test_update_system.py -m ui -o addopts=
```

GitHub Actions runs the core tests and the Playwright UI suite on fresh Ubuntu
runners for each workflow run.

The repository currently declares no release-specific data migrations. The
updater tests therefore verify preservation through the no-migration path; a
future release migration must add a migration-failure rollback scenario before
it is shipped.
