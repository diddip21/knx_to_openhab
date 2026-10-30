# Probe harness adoption — code/test/doc only

## Status and scope

Prepared for independent adoption review. **NOT deployed and NOT runtime-accepted.**
No WSL command, guest app/unit operation, candidate, new probe UUID, reboot,
reset-failed, provider marker recreation, or readiness/repair checkpoint was run.
The historical real probe exit 1 remains unchanged. This work does not claim a
successful migration/update or a successful new confinement probe.

The callback review is the ignored controller document
`.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/probe-timeout-fix-review.md`,
especially lines 181–229. Its approval is not approval of this new dispatcher.

## Adoption boundary

- New explicit controller options: `--probe-harness-approval` and
  `--probe-harness-approval-sha256`, valid together for **probe only**. The host
  authenticates the bounded, duplicate-key-rejecting JSON before registration,
  preflight or transport. An independently supplied complete approval is required;
  the code neither enrolls an observed tree nor creates an approval/receipt.
- The new branch returns before the legacy fixture/state payload or preliminary
  `require_guest` call. Its guest Python is fresh, isolated (`-I -B`) and disables
  bytecode writes. Cached `scripts`, `installer`, test harness and private admin
  modules are refused rather than deleted, reloaded or patched.
- A stdlib-only verifier checks the entire pinned new tree **before the first
  installer/scripts/test-module import**. It checks canonical non-writable
  root-owned ancestors, exact file/directory inventory, uid/gid 0, directories
  0755, pinned file modes/hashes, regular singly linked files, no unexpected
  members/symlinks and changed-read rejection. The complete historical map digest
  authenticates names and modes, not merely a few selected callback files.
- The new dispatcher intentionally does not call either archived old-root import
  site. It uses the new tree's original provider/nonce/machine/mount verifier,
  exact custom paths and preparation guards, canonical repaired-source verifier,
  administrator origins, installed bundle hashes, and outside-NNP worker/sudo
  checks. Only then can it invoke the one selected callback. Module `__file__`,
  callback `co_filename`, adapter constructor `co_filename`, trusted namespace
  paths and imported trusted-support hashes are checked. A future authorized
  invocation prints the verified origins/pins before the callback.
- Bootstrap, readiness, repair and all other phases retain their previous default
  path. Omitting the new options retains the old probe behavior. No production
  code, units, defaults, worker policy or old immutable tree was edited.

## Exact reviewed inputs (not current mutable HEAD)

| Input | Exact identity |
|---|---|
| Callback harness commit | `0976f1025fabfb12633174cfb5422e1c136d59a9` |
| New exclusive destination | `/opt/knxoh-harness-0976f10` |
| Full tar SHA256 (`git -c core.autocrlf=false archive --format=tar <full commit>`) | `0ff17eb022f058cfb41e1284b27b1d86516561bbe46b45f4f595cc8ab7b7deaf` |
| Complete 269-file map SHA256 (sorted compact JSON) | `4cbd7e9ea56f3322e9b140403b49a465e0ded8bd91a3f11d3a7f4eaee28841d1` |
| Callback file `tests/integration/test_update_systemd.py` SHA256 | `9ced721b4428b296cee7f62f342cba6ade0a91c009136f8b191d50c4364b41dc` |
| Adapter `installer/update_core/systemd.py` SHA256 | `1f53d9b0a2951ffeb373704d47df6b97d665f6a967f21d34ebac8e6c134d9e0f` |
| Unchanged production source commit | `2dcf3078b61283a41fd1ef38e34327e4f759d5c1` |
| Unchanged production approval SHA256 | `90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea` |

The separate harness approval schema is exactly `format: 1`,
`purpose: "probe-only-reviewed-harness"`, `head`, `root`, `archive_sha256`,
`review_approved: true`, and the complete `files` map of `{sha256, mode}` entries.
It is **not** the production approval or the original provider receipt. The
portable tests reconstruct its map from the full historical archive; no private
keys/nonces/receipts are committed. The source approval is accepted only with
its original canonical serialization pin, then verified with the unchanged
canonical baseline/delta source guards inside the guest.

### Dispatcher bytes ready to review/pin, not yet approved

These are SHA256 of the LF file bytes (also the Git blobs), separate from the
0976f10 callback archive:

- `scripts/run_nested_systemd_acceptance.py`:
  `577b79924e5f334d5b556db5e4a2973974703da62ac0a32b9ed06ae3b4dffe47`
- `scripts/probe_harness_adoption.py`:
  `e592462094abd5cbe1dc2fd4195cdb52b8f929f66edc5304cc7a744b8bd672d8`
- `tests/test_probe_harness_adoption.py`:
  `0d0b29ca879dc7e3d118dd5438569671edc08d2016fb42db9d8b4d8d492f31e5`

Actual deployed `__file__`/`co_filename` observations remain **pending**, not
inferred from these offline pins. Expected callback and adapter origins are the
two relative paths above under the exact new root.

## Red/green and validation

Environment: local Windows Python 3.11 (not target Linux Python 3.12/3.13).

- RED, before implementation: `python -m pytest
  tests/test_probe_harness_adoption.py -q -o addopts=` exited 1 during collection:
  missing `scripts.probe_harness_adoption` (1 collection error).
- Initial GREEN: same command, **14 passed**. Expanded full-inventory test then
  exposed the Windows archive CRLF difference: **1 failed, 31 passed**. Using
  explicit `core.autocrlf=false` for both historical archive reads fixed the
  fixture rather than weakening verification.
- Final GREEN: `python -m pytest tests/test_probe_harness_adoption.py
  tests/test_nested_probe_source.py tests/test_nested_systemd_fixture.py
  tests/test_nested_fixture_source.py tests/test_nested_fixture_continuation.py
  tests/test_nested_repair_health_contract.py tests/test_nested_acceptance_guard.py
  -q -o addopts=`: **246 passed in 9.80s** (final rerun).
- New portable coverage: wrong tree/map, cached old modules, wrong actual module,
  callback and adapter origins, wrong callback/adapter file bytes, wrong source,
  unexpected member, symlink, hardlink, owner/ancestor and missing-file refusal.
  Tree failures reach no imports/effects. A genuine historical inventory and real
  origin verifier reach only a spy callback after provider/path/preparation/source/
  helper/worker/sudo guards; each guard refusal excludes that callback. This is
  offline adoption evidence, not simulated runtime acceptance.
  The historical map comparison also proves every `installer/` file and mode in
  harness 0976f10 equals the unchanged production-source approval's corresponding
  map. `git diff --stat <2dc full commit> <097 full commit> -- installer` is empty.
- `python -m black --check .`: **passed**, 153 files unchanged.
- isort `--check-only` and flake8 over all Git-tracked Python files plus both new
  Python files: **exit 0 each**. Naive whole-directory isort/flake8 attempts timed
  out at 120 seconds while traversing ignored scratch virtualenv dependencies;
  no unrelated files were reformatted.
- Related repair-suite attempt timed out at 120 seconds as part of a larger
  selection; `python -m pytest tests/test_nested_fixture_repair.py -q -o addopts=`
  also timed out at 300 seconds after progress, with no passing-summary claim.
- Default `python -m pytest -q`: **not green**, exit 1; observed unrelated Windows
  POSIX-path/directory-FD, fchmod/fchown, symlink privilege and private-mode
  failures. It unexpectedly included UI tests and spawned local test backends;
  those processes are no longer running. The local pytest parent was explicitly
  stopped after failures were collected, so no complete count is claimed. Its
  generated screenshots/dummy file were removed and its sole `config.json` key
  reorder was restored. No guest application/backend was started or contacted.
- No separate live UI/guest acceptance run is authorized or claimed. No UI was
  changed, so no finished-interface screenshot deliverable applies.
- `git diff --check`: passed before report; repeated before commit.

## Deployment and next gate

**Deployment deferred for independent review.** No archive was copied and no
guest receipt/marker was created or replaced. Existing d1/829/source trees and
the live fixture were not inspected or touched during this stage; preservation
is not claimed as a fresh runtime observation. No new readiness checkpoint exists.

Still required: controller review/pins of these new dispatcher bytes; a separately
approved full harness manifest and its raw SHA256; fresh original-provider
registration and outer/inner preflight plus root nonce/hash receipt; independently
reviewed archive-member-safe exclusive deployment to the NEW destination; exact
deployed complete-inventory/hash/metadata verification and evidence that old d1,
829, pinned production source, installed/config state (including protected config
3354) and historical receipts remain unchanged. Never reuse the old deploy script
or recreate the provider marker. Archive copying/extraction is deliberately not
implemented by this probe dispatcher.

Only after that adoption review and renewed explicit controller authorization may
there be ONE actual probe with a NEW UUID/roots and NEW exclusive evidence, retaining
both old and new artifacts. No retry, readiness, repair, app update or other scope
is implied. Current local broader-validation limits must be resolved or explicitly
accepted by the controller before any deployment gate is considered green.
