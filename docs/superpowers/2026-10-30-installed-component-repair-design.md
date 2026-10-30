# Named EnvironmentFile installed-component repair

Status: runner design/code review required; **no runtime authorization**. Production
fix is separately owned. This document implements the controller's explicit
runner-only request, not permission to enroll or repair the guest now.

## Approach and boundaries

Use a new `repair-environmentfile` phase with an externally SHA-pinned, privately
held exact installed-state checkpoint. Reusing fresh/after-sudo is forbidden;
generic force/resume or automatically blessing a newly observed snapshot would
adopt unknown state. A named transition with a frozen allowlist is the only
permitted approach. No production files/tests are part of this runner change.

The checkpoint is `environmentfile-installed-20261030`, bound to this provider's
machine/boot and original receipt hash. It records metadata, device/inode and
streamed file digests for the full installed footprint, including all **3354**
initial-release entries. Hashes only: never raw credentials or nonce. The original
provider receipt remains separately private. No exporter that accepts arbitrary
observed state as approved is provided. The controller must independently inspect
and approve the exact snapshot, pin its bytes outside the guest, and review both
code changes before any guest operation. Recorded logs alone do not supply missing
file hashes/inodes; no values will be guessed or fabricated.

## Preconditions and transition

1. Native registration and existing outer preflight remain mandatory. Inner guard
   authenticates original receipt, IDs, private-network/mount/kernel context.
2. Validate strict checkpoint schema; full inventory equals approved snapshot.
   Bind exact accounts/groups/aliases and localhost, original config/generator/
   paths hashes/modes, private credential metadata/hashes, current's exact absolute
   initial target, full frozen root-owned link-free initial source/venv (3354).
   Empty jobs/staging/generated/backups and protected preparation/state directories;
   no journal, gate, maintenance, transaction or unknown sibling artifacts.
3. Verify complete retained immutable 47e2c3a source using its pinned manifest.
   Installed bundle/helper/policy/tmpfiles/unit/drop-in bytes must equal that actual
   source and old renderer, not merely a freshly collected hash. Unknown bundles,
   defaults, prefixed units and links refuse. Initial release content must match
   old source outside its administrator-created venv; dependency contract unchanged.
4. Verify explicit future full production commit and strict manifest, immutable new
   root; purpose `reviewed-environmentfile-fix-source`, based on 47e2c3a. No implicit
   current worktree/HEAD selection. Old source retained. Only bootstrap rendering
   and its unit regression files may differ from the pinned old production map.
5. Require stopped UI/cleanup service/timer and updater, MainPID zero, no queued
   manager jobs for any own unit. Recovery must be active/exited, successful. Pin
   full queried states (including results/restart counts) in checkpoint.
6. Open retained lifecycle lock **without O_CREAT**, check inode/metadata, acquire
   LOCK_NB and inherited real admin lease. Repeat guest, complete inventory, old/new
   source, installed old hashes and manager-state checks under lock. No application
   mutation before all checks pass. Use verified new admin `check_worker`,
   `check_worker_sudo`, then **only `install_components`**. Existing state needs no
   provision_state call (it would chmod/chown the mutation lock); no venv rebuild,
   initial preparation, credential rewrite, candidate execution or package install.
7. While locked, verify external/runtime/initial trees and their inodes unchanged;
   verify new installed components against new source/renderer. Production helper
   retains the old bundle under its own protected random name; retain it, and
   require exactly one such newly created directory with old bundle bytes.
8. Release lock before real production `activate_services`: daemon-reload,
   recovery, notify UI, cleanup timer. Query actual service state and HTTP
   `/health` on 127.0.0.1:8085 (no injected environment, replacement unit or path).
   Activation/readiness failure stops only own UI/cleanup writers, prints actual
   manager state and preserves failed results/artifacts; no fresh retry, reset,
   rollback or automatic adoption. Later repair checkpoints require new names.

## Verification and remaining acceptance

Portable TDD uses synthetic exact inventories and effect spies, not systemd/WSL.
Cover stale inode/hash/mode/identity/current/receipt/boot, extra children/defaults,
journal/gate/maintenance, active writers/queued jobs, missing pins/source review,
under-lock races, policy refusal, preserved state, lease release before activation,
activation failure stopping writers, strict phase dispatch and source delta limits.
Formatting/lint and focused tests only; no full native core suite.

No runtime snapshot enrollment, source deployment, manager commands or app guest
effects in this delivery. After separate reviews and explicit runtime authorization,
remaining original acceptance still includes child sandbox/cgroup/resource proofs,
actual nested reboot/offline lock, authenticated API and real notify readiness,
trusted local HTTPS update/no-update/checksum/rollback/fresh retry, repair/races and
full applicable Linux suite. Task 5 remains incomplete.

## Delivered interface (offline-tested; DO NOT run before controller review)

The existing controller gains `--phase repair-environmentfile`, requiring all of:

- `--receipt`: original private provider receipt (existing current registration and
  outer preflight run before any inner invocation).
- `--checkpoint` and `--checkpoint-sha256`: independently reviewed exact checkpoint
  bytes, SHA-256 pinned outside the guest; no installed-state exporter/enroller is
  added. The obsolete `checkpoint-inventory` phase still accepts only its original
  after-sudo partial state and cannot authorize this transition.
- `--source-approval`, `--source-approval-sha256`, `--approved-source-head`: explicit
  NEW full immutable production commit, complete manifest and external bytes pin.
- `--evidence-dir`: the existing controller's private evidence directory.

Checkpoint schema (strict keys): `format: 1`,
`checkpoint: environmentfile-installed-20261030`, `nonce_sha256` (not raw nonce),
`old_source_approval` (the original complete 47e2c3a manifest), and `inventory`.
Inventory keys: `entries`, `accounts`, `groups`, `aliases`, `hostname`, `machine_id`,
`boot_id`, `manager`. Entries contain kind/UID/GID/mode/device/inode/link count and
either streamed SHA-256, sorted children, or exact allowed link target. No credential
or raw receipt content is exported. Root-only `collect_installed()` is an internal
read-only collection primitive, not approval of its result; any future collection
must first pass current provider/inner receipt guards and independent review.

`manager` contains `units` (all five fixed units, full queried properties) and
`jobs` (own application-prefixed queued jobs, necessarily empty). Properties are
LoadState, ActiveState, SubState, MainPID, Result, ExecMainStatus, NRestarts and
UnitFileState. Absent service-only timer properties normalize to `0`; returned
values are not overwritten. Read-only queries and each guarded install precondition
are repeated under the original existing-inode lifecycle lease.

The retained `.updater-mutation.lock` is intentionally root:989 **0660**, not 0600.
It is opened read-only/no-follow through its protected parent and pinned without
chmod/chown/create. Config projections, private state/preparation directories and
the five original empty generated files are included; no pending journal/gate/
maintenance, runtime job, unknown sibling, default installation or retained bundle
is approved. All 3354 initial-release entries are required and compared exactly.

Original source file-map canonical JSON SHA-256 (sorted keys, compact separators):
`34692929a224a22a53d6bd87aa48098ad98bbbcd023d2b741432f92ce3d2ea8e`.
Original archive SHA-256:
`1a02d8a3e89f23052aee137aa57f0f3321aa9d15da79af828368a527d2695676`.
These are frozen from the retained original controller approval, not guest-learned
observations. New source purpose is `reviewed-environmentfile-fix-source` and
production_base is the full old `47e2c3a3cd59d716f793226ec17badde60999eca`.

Only `installer/update_bootstrap.py`, `tests/test_update_units.py` and
`tests/integration/test_update_environment_runtime.py` may differ in the new full
file map. Bootstrap must differ; no removals or mode changes are permitted. Prepare
a separate reviewed production tree/commit based on old production: a manifest of
the current workrepo's later HEAD includes unrelated runner/docs changes and will
correctly refuse. Do not relax this restriction to deploy the harness as production.
Deploy the reviewed harness separately; never edit either immutable source in place.

Portable tests use real offline files plus descriptor/manager fakes. They establish
ordering, refusal, streamed digests and inode preservation, **not** Linux no-follow,
systemd, WSL or actual application-readiness acceptance. Independent controller
production and runner reviews, fresh guarded private checkpoint collection/pinning,
and explicit runtime authorization remain prerequisites. Nothing in this delivery
collects or repairs the guest, reruns the environment, or completes Task 5.
