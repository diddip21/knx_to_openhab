# Nested systemd acceptance: provider checkpoint (2026-10-30)

Production source under test: `27d106a26c907b7ce05d1880ea25157b1f815e50`.
**No installed-unit acceptance completed; parent Task 5 remains incomplete.**
The original driver-share blocker below is superseded by the controller's
explicitly authorized narrow outer-only policy. Live read-only preflight and
source-only transfer now pass. Independent guard review is the next checkpoint;
**application provisioning and hazardous acceptance have NOT run**.

## Guard-review corrections (pending rereview)

- The hazardous harness reads `/proc/sys/kernel/osrelease` independently of
  `systemd-detect-virt`. A WSL/Microsoft kernel, detection result `wsl`, presence
  of the fixed provider receipt (including an unsafe/broken leaf), or explicit
  `KNXOH_DISPOSABLE_SYSTEMD_PROVIDER=fresh-wsl2-nspawn` selection requires the full
  nested receipt/nonce/identity/PID-1/mount/interop checks, regardless of the
  detector reporting `systemd-nspawn`, `docker`, `kvm`, or another layer. Missing
  kernel evidence fails closed. A genuinely non-WSL VM/container without explicit
  nested-provider context retains the existing generic disposable guard flow.
- Outer WSL configuration requires the literal value `false` for each required
  section-local key. Interpolation is disabled, nonempty `[DEFAULT]` is rejected,
  and malformed/duplicate/inherited/interpolated settings cannot reach the inner
  query. The recorded literal configuration and exact outer driver policy remain
  accepted; the driver-share exception itself is unchanged.
- Guest provider receipts are now read from one bounded no-follow opened regular
  inode through the existing trusted `secure_fs` primitives. Root-owned,
  non-writable ancestry, root-only leaf mode, pinned directory entries and stable
  leaf metadata are required; no stat-then-path-reopen authenticates the read.
  This hardening is harness-only: no production loader or filesystem primitive
  was changed. Portable tests model rejected unsafe ancestry/replacement and the
  pinned reader boundary; they are not a real POSIX race acceptance run.

Trust limits remain explicit: generic marker/configuration paths require trusted
root-owned, non-writable containing directories; their existing readers were not
redesigned. The Windows receipt remains trusted operator input. Preflight binds
explicit invocation to observed machine IDs, not a cryptographic nonce challenge
or proof of fresh import, absence of every host channel, or runtime namespace
enforcement. No protection against a malicious guest administrator is claimed.

The explicitly authorized fresh WSL2 distribution has a real nested nspawn systemd
manager with an independent machine ID. The new read-only preflight rejected the
outer guest on the initial attempt before source transfer or application provisioning: WSL automatically
mounted its read-only driver share via `9p` at `/usr/lib/wsl/drivers`, even with
automount and interoperability disabled. The required strict no-9p policy rejects
that share. This is not evidence of a C: user-data mount, a production updater bug,
or failed inner sandbox isolation; it is an unmet provider prerequisite.

No outer filesystem unmount, host fallback, service/account/policy installation,
root candidate execution, default-distribution change or WSL shutdown/terminate
was attempted. Existing Ubuntu and Windows host state were not modified. No
production updater/installer/application code changed.

## Authorized narrow outer driver policy

After receipt, registry/location and outer machine-ID validation, the outer
preflight allows at most one `9p` record with root exactly `/`, target exactly
`/usr/lib/wsl/drivers`, source exactly `drivers`, VFS flags containing `ro,nosuid,nodev`
and no `rw`, and superblock flags containing `ro` and no `rw`. All other `9p`/`drvfs`
records, additional shares, malformed fields, changed source/root/path/type,
missing safety flags or writable variants are refused before contacting the inner
manager. Inner `9p`/`drvfs` remains forbidden, including that exact driver share.
Interop and WSL automount/interop configuration checks remain mandatory. This is
not a generic WSL permission, a writable driver exception or a host unmount.

Mountinfo is parsed as complete records (IDs/device, paths, optional fields,
filesystem/source and separate VFS/superblock options). Kernel-reported unlinked
tmpfs bind-source roots may contain `//deleted`; they are not candidate paths to
canonicalize. The driver root comparison remains byte-for-byte `/`.

With portable tests green, the explicitly named outer and nested read-only
preflight passed. Native `git -c core.autocrlf=false archive 27d106a` was transferred
to the new nested `/opt/knxoh-source-27d106a`, not the previous source tree. All
**238 files** were independently hash-checked inside the nested guest. Archive
SHA-256: `a31060570bd5f0539a8acdc0831a9d44fed6fc39f816b1d3e9ad688c09a764ae`.
The root-only adjacent source receipt records the exact production commit and
verification; it does not attest acceptance, reboot or offline lock absence.

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

The provider extension and new narrow policy require independent review before
use for application effects. No further provisioning is authorized at this
checkpoint. No boot/offline attestations were created.

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

- Final focused guard command plus `tests/test_update_sandbox.py` and
  `tests/test_update_secure_fs.py` after review corrections:
  **303 passed, 58 skipped** (three real-manager tests, five POSIX sandbox tests
  and fifty POSIX filesystem tests on Windows). Read-only preflight passes again;
  no updated harness transfer/application setup occurred. RED first showed
  3 failures/29 passes for the original policy
  cases; the real kernel tmpfs bind-root regression separately failed before its
  parser correction. Neither test run contacted a live manager.
- Native Windows/Python 3.11 core: **21 failed, 795 passed, 681 skipped**. Failures
  involve POSIX paths, permissions, symlinks and unavailable `fchmod`/`fchown`;
  all failure names/raw output are retained in the private report. This is not
  Linux/Python 3.12 acceptance, nor a claimed clean baseline.
- Black/isort/flake8 over all **137 tracked-plus-new Python files**: passed.
  Bare recursive isort/flake8 initially scanned existing ignored scratch venvs
  and snapshots and failed; those artifacts were not changed.
- `git diff --check`: passed, with native Git LF/CRLF warnings.
- UI tests and Linux full-core rerun: not run. The expensive native core suite
  was not rerun for this guard-only revision; its recorded result above is historical.
