# Own-nspawn runner corrections and explicit continuation

Scope: runner/tests/docs only. No guest execution in this revision. The production
sudo fix is owned/reviewed separately. This plan does not certify acceptance.

## Destination and fresh-state gates

- Probe requires exact `Paths(BASE/releases, BASE/current, CONFIG, DATA, BACKUPS)`
  equality after the protected production loader, before any hostile callback.
  Its fixed `/var/lib/knxohupdate-preparation` parent must be a real root-owned
  mode-0750 directory, group `knxohupdate`, with trusted non-writable ancestry.
- Fresh bootstrap inventories the complete footprint before hostname, account or
  file changes: custom directories, account and group names, both paths contracts,
  libexec/staging bundles, units/drop-ins/enabled links, policy/helper/tmpfiles,
  preparation and fixture credentials. Dangling links count as existing state.
  No artifact is removed/adopted. An existing lifecycle lock is an explicit
  root:root mode-0600 single regular inode prerequisite, never unlinked.

## `resume-after-sudo`: one named checkpoint, not a force option

This route is only for `after-sudo-denial-20261030`. It never calls fresh seeding.
Before effects, repeat the approved provider/receipt/live inner guard, then check:

- Hostname `localhost`, exact recorded `/etc/hosts` bytes, the original root-only
  provider receipt/nonce and the unchanged nested machine ID.
- UI UID/GID `999/989`, worker `997/988`, respective sole memberships, group names
  and empty explicit member lists, nologin shells and `/nonexistent` homes.
- Exact directory enumeration/UID/GID/modes: root-owned app/releases/output,
  root:UI config, UI-owned data/backups and the three empty data subdirectories.
  Config contains only `config.json`, `generator.json`, `paths.env`; releases,
  output, backups and data subdirectories are empty. All other application
  installation artifacts, `current`, secrets and venvs must be absent.
- Exact original config/generator/paths hashes and ownership/modes; never rewrite
  these files or migrate away sibling settings to make a checkpoint fit.
- A controller-pinned private checkpoint manifest additionally binds every known
  entry's device/inode and the retained lock. It is not generated/adopted by the
  resume route. A separate read-only inventory function may produce a candidate
  manifest only AFTER the hard-coded recorded-state checks pass; controller pins
  its SHA-256 outside the guest. No enrollment is executed in this revision.

The controller supplies a separately approved production-source manifest plus its
SHA-256 and explicit full new commit ID. Its exact schema declares the baseline,
review approval, fixed `/opt/knxoh-source-<full-commit>` destination, archive SHA-256
and complete relative-file SHA/mode map. Verify the entire root-owned link-free
source tree/ancestry, no extra files/directories, and unchanged original dependency
contract before importing its administrator bootstrap in a distinct module.
Neither old immutable source/harness nor production files in this checkout are
edited. A manifest Boolean alone is not approval: the supplied out-of-guest pin
and commit are the trusted controller's explicit reviewed-source decision.

After all read-only checks pass, acquire the retained lifecycle lock through the
new verified administrator module, confirm the locked descriptor is the pinned
inode, and repeat checkpoint/source checks under that lease. Repeat real worker
identity and sudo-policy checks before state/bundle/environment provisioning.
Retain the lease throughout disk preparation; release it before starting recovery
and writers, avoiding recovery's lock dependency cycle. Unknown state/refusal
causes no repair/delete or partial-config overwrite. A later failure retains its
own new evidence; this checkpoint route must refuse a partially executed tail.

## Verification and stop boundary

Portable tests cover canonical off-fixture probe destinations/preparation refusal,
stale artifacts/group-only fresh states and dangling links, and continuation
metadata/hash/UID/membership/unknown-entry/pin/source refusal before effects.
No production manager, guest preflight, app setup, core suite or UI suite is run.
Controller rereviews runner and production changes before authorizing execution.
All original real boot, units, TLS/update/rollback, readiness, child confinement/
cgroup teardown, resources, repair/races and final review obligations remain open.

## Exact checkpoint file contract

`recorded_specs()` in `scripts/nested_fixture_state.py` is the non-configurable
allowlist. These hashes are derived from the recorded seed program and immutable
27d106a Git bytes, **not newly observed guest metadata in this revision**:

| Entry | UID:GID / mode | SHA-256 |
|---|---|---|
| `CONFIG/config.json` | `0:989 / 0640` | `9b03b0c51488741d51b6a982b038cd32f5b3d09b4d6d84c925b8ca6d5594ef70` |
| `CONFIG/generator.json` | `0:989 / 0640` | `bd38d4c92a329e5ac4c8de12b5d7966d7aedf79625c12d89d91f15e1116c6d73` |
| `CONFIG/paths.env` | `0:0 / 0644` | `2cfc6d576156ad443b722370e15196d2d9806c0ea601939a5e83f52b4f07177d` |
| `/etc/hosts` | `0:0 / 0644` | `43828ab06a236fcc33f2430a80c0c161538c5e2100d28e9732ff16811dd148c9` |

App root, releases and output are `0:0 / 0755`; config is `0:989 / 0750`;
data/backups and jobs/staging/generated subdirectories are `999:989 / 0750`.
The regular, singly-linked root receipt is `0:0 / 0600`; its exact byte hash is
derived privately from the original receipt serialization and existing nonce.
The retained singly-linked lock is `0:0 / 0600`, with the SHA-256 of empty bytes.
Directory children are enumerated exactly by the code; any extra entry blocks.
Private device/inode values must be inventoried and pinned after rereview. If
actual state differs from these assumptions, inventory refuses: no repair or
new snapshot can silently redefine this checkpoint.

## Manifest schemas and future controller commands

Private checkpoint schema has exactly `format=1`,
`checkpoint="after-sudo-denial-20261030"`, the fixed `machine_id`, original `nonce`,
and `inventory` (exact entries/accounts/groups/aliases/hostname). The read-only
candidate is not approval and is never echoed with its nonce to the console.

Reviewed-source schema has exactly:

```json
{
  "format": 1,
  "purpose": "reviewed-sudo-fix-source",
  "head": "FULL_NEW_REVIEWED_COMMIT",
  "production_base": "27d106a26c907b7ce05d1880ea25157b1f815e50",
  "review_approved": true,
  "root": "/opt/knxoh-source-FULL_NEW_REVIEWED_COMMIT",
  "archive_sha256": "NATIVE_IMMUTABLE_ARCHIVE_SHA256",
  "files": {"RELATIVE_PATH": {"sha256": "FILE_SHA256", "mode": 420}}
}
```

Placeholders are not accepted. All files must appear; modes are decimal 420/493
(0644/0755). Directories are derived from that map and must be root:root 0755,
without extras. Original `requirements.txt` hash must remain
`836f5d08439f7a536cae171993c199821a95d1face231826a49bb0043a5829fe`.
Source version must be 0.1.0. The controller's explicit manifest-byte SHA-256 pin
and approved full commit are checked before contacting the guest; inside it the
complete tree/hash/ownership is rechecked, including under the retained lease.
The archive hash records native archive provenance; the guest verifies the full
file map, not a fictitious in-guest archive which was never retained there.

After both reviews authorize runtime (none of these commands ran in this change):

```powershell
python scripts/run_nested_systemd_acceptance.py --receipt <private-receipt> --evidence-dir <private-evidence> --phase checkpoint-inventory
python scripts/run_nested_systemd_acceptance.py --receipt <private-receipt> --evidence-dir <private-evidence> --phase resume-after-sudo --checkpoint <checkpoint-candidate.json> --checkpoint-sha256 <controller-pin> --source-approval <reviewed-source.json> --source-approval-sha256 <controller-pin> --approved-source-head <full-reviewed-commit>
```

The existing `probe` phase can take the same source approval/pin/commit (without
checkpoint flags) to run policy validation from the newly reviewed administrator
module rather than accidentally reusing the old cached bootstrap. It still
requires exact fixture paths and the installed preparation-parent prerequisites.
No flag grants broad resume, selects a branch/current worktree, deletes state,
or replaces the separately deployed reviewed guard. All runtime paths remain
unexecuted until controller authorization after rereview.

Revision verification: **85 portable tests passed** across
`test_nested_systemd_fixture.py`, `test_nested_fixture_continuation.py` and
`test_nested_fixture_source.py`. Black/isort/flake8 passed for all six changed
runner/test Python files. These use synthetic inventory/effect spies and bounded
native temporary manifests, not a real manager or POSIX race experiment. No WSL
invocation, guest preflight, enrollment, deployment or application effect occurred
in this revision. No production code/tests were edited. Runtime remains pending
the separate production review and runner rereview.
