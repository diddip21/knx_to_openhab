# Nested systemd acceptance: blocked at provider preflight (2026-10-30)

Production source under test: `27d106a26c907b7ce05d1880ea25157b1f815e50`.
**No installed-unit acceptance completed; parent Task 5 remains incomplete.**

The explicitly authorized fresh WSL2 distribution has a real nested nspawn systemd
manager with an independent machine ID. The new read-only preflight rejected the
outer guest before source transfer or application provisioning: WSL automatically
mounted its read-only driver share via `9p` at `/usr/lib/wsl/drivers`, even with
automount and interoperability disabled. The required strict no-9p policy rejects
that share. This is not evidence of a C: user-data mount, a production updater bug,
or failed inner sandbox isolation; it is an unmet provider prerequisite.

No exemption, outer filesystem unmount, host fallback, service/account/policy
installation, root candidate execution, default-distribution change or WSL
shutdown/terminate was attempted. Existing Ubuntu and Windows host state were not
modified. No production updater/installer/application code changed.

## Reproducible read-only checkpoint

`scripts/nested_acceptance.py` requires an administrator's private fresh-import
receipt and verifies the explicitly named WSL2 registration/location, outer and
inner machine IDs, disabled host integration, nested PID-1 container evidence and
mount types. It does not provision, reboot, install dependencies, or claim that a
receipt proves namespaces. Run from Windows:

```powershell
python scripts/nested_acceptance.py --receipt <private-provider-receipt.json>
```

Receipt format 1 has **exactly** these fields:

- `format`: integer `1`; `provider`: `fresh-wsl2-nspawn`.
- `distribution`: `KNXOH-Acceptance-20261030`; `machine`: `knxoh-acceptance`.
- `install_location`: the exact approved fresh-import path encoded in the script.
- `outer_machine_id`, `inner_machine_id`: different nonzero lowercase 32-hex IDs
  recorded from that fresh import, not invented to match the running machine.
- `nonce`: an independent, nonzero lowercase 64-hex random nonce.

For the real-manager pytest harness, install the receipt inside the nested guest
as root-owned regular mode-0600 `/etc/knxoh-nested-acceptance.json`, with its nonce
equal to the existing disposable marker/config/environment nonce. This narrowly
handles `systemd-detect-virt` returning `wsl` even inside nspawn; ordinary/unmarked
WSL and nonvirtual hosts remain refused. The other existing gates, actual boot
change and independently observed offline lock absence remain mandatory. **Do not
create boot/offline attestations until those events have actually occurred.**

The provider extension requires independent review before use for application
effects. Resolving the outer driver share needs an authorized provider change or
explicitly reviewed narrower policy, not silently bypassing the guard.

## Evidence and limits

Private incremental report (ignored, with exact commands and diagnostic output):
`.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/wsl-acceptance-report.md`.
Private receipt/nonces and raw provider artifacts are not committed.

Portable guard tests use synthetic evidence and never invoke WSL or a manager:

```sh
python -m pytest -q tests/test_nested_acceptance_guard.py tests/integration/test_update_systemd_guard.py tests/integration/test_update_systemd.py -o addopts=
```

Remaining proof includes the original three real-manager tests, full installed
update/rollback with production dependencies and Gunicorn, strict local HTTPS
fixtures, actual reboot/offline-lock ordering, same-boot/crash recovery, descendant
cgroup teardown, resource exhaustion, repair and independent review. None is
satisfied by portable guard tests, static unit properties, inherited baseline
probes or this preflight refusal. See `tests/integration/README.md` for obligations.

Verification at this checkpoint:

- Focused command above: **148 passed, 3 skipped** (the three real-manager tests).
- Native Windows/Python 3.11 core: **21 failed, 795 passed, 681 skipped**. Failures
  involve POSIX paths, permissions, symlinks and unavailable `fchmod`/`fchown`;
  all failure names/raw output are retained in the private report. This is not
  Linux/Python 3.12 acceptance, nor a claimed clean baseline.
- Black/isort/flake8 over all **137 tracked-plus-new Python files**: passed.
  Bare recursive isort/flake8 initially scanned existing ignored scratch venvs
  and snapshots and failed; those artifacts were not changed.
- `git diff --check`: passed, with native Git LF/CRLF warnings.
- UI tests and Linux full-core rerun: not run at this blocked checkpoint.
