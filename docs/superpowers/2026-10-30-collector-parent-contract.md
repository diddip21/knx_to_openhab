# Installed repair: shared policy-parent collection contract

Status: code and new pending checkpoint require independent review. **No repair,
activation, deployment or controller pin approval is supplied by this change.**

The actual read-only 3421-entry collection at `c0e381c` could not satisfy the full
component validator: policy files were collected, but `/etc/sudoers.d` and
`/etc/tmpfiles.d` were not. The generic `.d` validator also incorrectly assumed
those shared system directories were exclusive app drop-ins with mode 0755.

## Narrow contract

One declaration in `scripts/nested_fixture_repair.py` specifies both required
shared parents and their exact known-state policies:

| Parent | UID:GID | Mode | Required application-prefixed child |
| --- | --- | --- | --- |
| `/etc/sudoers.d` | 0:0 | 0750 | `knxohui` |
| `/etc/tmpfiles.d` | 0:0 | 0755 | `knxohui.conf` |

These are the actual observed protected parent modes, not permissions applied by
the runner. Collection opens existing directories through the real secure_fs
ancestor/no-follow descriptor chain, verifies stable metadata/name enumeration,
and records device/inode/ownership/mode/link count and sorted child names. It does
not create, chmod, chown, replace or recursively hash the shared directories.

Unrelated system-policy sibling names may exist and are pinned as names only;
their contents are neither read nor adopted as application components. The
application-prefixed child set must match the declaration exactly. Unknown own
policy names, unsafe metadata, symlinks, missing parents and stale inodes refuse.
Unit drop-in directories remain exclusive with their existing exact child rules.
Installed component file hashes/modes and original external/initial state checks
are unchanged. The collector's symlink race comparison excludes only access time,
which readlink itself can update; identity and mutation metadata remain checked.

## Verification

`tests/integration/test_nested_fixture_collection.py` runs the **real collector**,
JSON serialization, checkpoint validation and full installed-component validation
inside a temporary Linux chroot with the fixed fixture paths. It builds all 3354
initial entries as real files/directories. No inventory entries are synthesized,
filtered or appended after collection. Account/manager identities and trusted seed
hashes are explicit test fixtures; actual Linux filesystem/descriptor/inode checks
and actual kernel fdinfo remain in use. No mount, account or app-manager change is
made. Root/private temporary files are the only test writes.

The regression covers unrelated genuine policy siblings, wrong UID/GID/mode,
symlink parents, extra application policies, replacement parent inodes and a link
swap during collection. Windows skips this Linux/root-only integration test.

Guarded read-only verification in the authorized own inner guest produced a NEW
pending **3423-entry** snapshot: all original 3421 entries, all manager properties
and all **3354** initial entries exactly unchanged, plus two genuinely collected
parents. Full old-source/component validation passed. Raw evidence and the new
pending checkpoint remain outside the guest in the ignored
`wsl-acceptance/collector-contract-c0e381c/` directory. The old pending checkpoint,
receipt and `repair-pin-report.md` are retained unchanged, not patched or replaced.

This is collection/validation evidence only. The original installed-writer runtime
RED remains; no notify/HTTP readiness, actual repair or parent Task 5 completion is
claimed. Independent code review and controller approval of the new source/harness
and pending checkpoint bytes must precede any newly authorized runtime action.
