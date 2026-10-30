# Fixed probe harness deployment composition — code review handoff

## Outcome / authorization boundary

**Implemented, tested offline, ready for independent controller review. NOT deployed.**
Base: `de13dd6044fff62ac5345ac30c74f963efb1a12e`. Only the new operator,
focused tests and this report are added. No existing tracked file was modified.
No subagents, WSL commands, guest commands, application services, production file
operations, native core suite or actual probe were run. The controller must review
the committed range and explicitly authorize execution; this self-review is not
independent approval. Historical probe exit 1 is unchanged.

The operator is executable transport, not another missing-transport proposal:
`scripts/deploy_probe_harness.py`. Its sole deployment destination and commit are
fixed. It never invokes any retained broader deployment operator. The only other
mode is a **separate read-only** `--origins-only` invocation, with its own NEW
external evidence directory. Neither mode invokes a callback.

Size tradeoff: the operator is 453 Black-formatted lines, above the soft 250-line
target. This includes the explicit old import-closure authentication, bounded tar
checks, controller transport and separate fresh-interpreter origin check. Rather
than conceal these behind an additional framework or reuse a broader operator,
they remain together for review. The existing pinned adoption verifier and old
protected-filesystem helper are reused; no general checkpoint system was added.

## Immutable inputs and code pins

| Input | SHA256 / identity |
|---|---|
| Operator raw LF bytes | `12500f0fd8dce6b19d1a0cca17fa46588a0ad3fee7cd63dcce2bd598516945f2` |
| Focused tests raw LF bytes | `7084559a054346b69f3d00f02a0a0e05f093b32e02f53fdf207c76960a3c8857` |
| Unchanged adoption verifier | `e592462094abd5cbe1dc2fd4195cdb52b8f929f66edc5304cc7a744b8bd672d8` |
| Unchanged host provider / old guard support | `0ddf4c4d5a552c487bc1e46c88d31ffe4fa5337f06db3bb86f5001e1eb3b95a1` |
| Fixed harness commit | `0976f1025fabfb12633174cfb5422e1c136d59a9` |
| Exclusive destination | `/opt/knxoh-harness-0976f10` |
| Native Git archive, 11,571,200 bytes | `0ff17eb022f058cfb41e1284b27b1d86516561bbe46b45f4f595cc8ab7b7deaf` |
| Complete 269-file map, sorted compact JSON | `4cbd7e9ea56f3322e9b140403b49a465e0ded8bd91a3f11d3a7f4eaee28841d1` |
| Full external approval raw bytes | `645f294d50f33eab28bc6b19b9b213d5e01f0d325e3d94c25a74787253cecc73` |
| Callback file | `9ced721b4428b296cee7f62f342cba6ade0a91c009136f8b191d50c4364b41dc` |
| Adapter file | `1f53d9b0a2951ffeb373704d47df6b97d665f6a967f21d34ebac8e6c134d9e0f` |
| Original host AND guest root provider receipt | `77fae5534ff26c51a920136735d4e59dcc55c3a397c895aae3424508a933ec1c` |
| Production source, NEVER deployed by this operator | `2dcf3078b61283a41fd1ef38e34327e4f759d5c1` |
| Original production approval, unchanged / not replaced | `90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea` |

The private PENDING tar/approval filenames from the preceding deployment report
are inputs, not newly generated approvals. The test reconstructs native archive
bytes with `git -c core.autocrlf=false archive --format=tar <full 0976 commit>` and
the complete approval serialization; both match the external pins above. The
operator itself performs no Git archive reconstruction or observed-tree enrollment.

The seven `OLD_FILES` pins are independently checked against historical
`d1f1848eab02f99cb436b620b22f0a0c1d0acdbb` Git blobs in the focused tests. They cover
the old guard module and its entire local import closure: provider, installer
initializers, protocol, systemd adapter and secure_fs. The operator does not deploy
the old harness or loop over production/harness roles.

## Self-review of the trust/effect order

1. **Host before transport:** fixed raw approval SHA plus duplicate-key/invalid-
   constant-rejecting JSON; exact reviewed approval schema/map; fixed raw archive
   SHA and full archive inventory; fixed original receipt SHA, original strict
   decoder/schema validator; pinned provider/verifier and explicitly supplied
   operator raw SHA. Then current original-provider registration and outer/inner
   preflight. There is no ambient checkout import for these controller helpers.
2. **Before target writes:** fresh guest `-I -B`; root required. Only the stdlib
   pinned adoption verifier is compiled. Old guard support bytes are read through
   its no-follow changed-read-checking reader after checking canonical root-owned,
   non-writable nonsymlink ancestors and leaf ownership. Parent identities are
   rechecked. Hardlinks are refused by that reader. Existing old bytecode caches
   and unexpected namespace initializers are refused, never removed. Exact source
   loader origins are checked before old imports, with actual top-level selection
   checked before importing the old test module. The original guest receipt must
   match the fixed raw pin and host object; then the **unchanged old trusted**
   `_check_virtualization` performs its original nonce/provider/PID-1/container/
   mounts/no-Windows checks. Inner machine ID and loaded local support origins are
   checked. Only then is its verified secure_fs helper returned for deployment.
3. **Authenticate all archive members before extraction:** at most 16 MiB raw tar,
   8 MiB per file, 298 entries; exactly 269 files and 29 directories matching all
   file hashes/modes and exactly their canonical parent directories. Only regular
   files/directories, uid/gid 0; exact native Git header modes 0664/0775 for files
   and 0775 for directories, normalized with `mode & 0755`. No links, sparse or
   special files, traversal/absolute/backslash/control/noncanonical paths,
   duplicates or extra/missing members. No extractall or pathname tar extraction.
4. **Exclusive protected creation:** the already authenticated OLD secure_fs
   `_parent` holds root and `/opt` descriptors and checks named/FD/mount identities;
   `/opt` is root-owned, nonsymlink, non-writable and gid 0. `mkdir` is exclusive,
   including for an existing symlink/file/empty directory. Every child is created
   relative to a held parent FD; directory opens use `O_NOFOLLOW|O_DIRECTORY`, file
   opens use `O_NOFOLLOW|O_EXCL|O_CREAT`. All bytes are written with a short-write
   loop, new directories/files are chowned 0:0 and chmodded 0755 / pinned 0644 or
   0755, files and all parent directories are fsynced, names/FDs and the ancestor
   chain are checked again. Failure retains artifacts; there is no replacement,
   deletion, adoption, rollback, retry or configurable destination.
5. **Completion before any NEW import:** pinned adoption `verify_tree` re-reads
   the complete deployed inventory/hashes/uid/gid/modes/link counts and rejects
   extras/changes. Deployment does not import the new tree at all. A successful
   result permits only a new **external** private deployment receipt; no guest
   receipt, provider marker or production approval is written. Adoption currently
   requires the manifest and actual root, not a harness-side deployment receipt.
6. **Separate read-only origins:** a NEW invocation/NEW evidence path repeats host
   pins/preflight. The original old guard runs in a child `-I -B` interpreter so
   its modules cannot contaminate the origin-check interpreter. Parent verifies
   the whole new tree, refuses cached trusted modules and ambient module/namespace
   selection, then explicitly imports the selected callback module and applies the
   reviewed actual `__file__`/callback `co_filename`/adapter constructor
   `co_filename` and support-origin/hash verifier. It reports actual origins but
   never calls the callback. This is not a migration or confinement probe.

External evidence directories must be new direct children of an existing approved
private controller directory (on Windows, inherited private ACLs remain a controller
prerequisite). Files are exclusively created with 0600 where supported, flushed and
fsynced; stdout is only a generic result. No nonce/key is printed. The external
receipt records operator, approval and complete-map pins, not provider authority.

## Exact red / green and static checks

Environment: local Windows Python 3.11. No Linux, WSL or guest execution.

- **RED before implementation:**
  `python -m pytest tests/test_deploy_probe_harness.py -q -o addopts=` — exit 1,
  1 collection error: missing `scripts.deploy_probe_harness`.
- First implementation run: **3 failed, 17 passed**. An initially chosen 4 MiB
  per-file bound rejected the authenticated 6,043,486-byte Charne fixture before
  any guard/write. Raised to a bounded 8 MiB; archive cap remains 16 MiB. This was
  an implementation limit correction, not weakening the archive/map pins.
- **Final focused GREEN:** same RED command — **45 passed in 7.41s**, exit 0.
- **Final related portable GREEN:**

  ```text
  python -m pytest tests/test_deploy_probe_harness.py tests/test_probe_harness_adoption.py tests/test_nested_probe_source.py tests/test_nested_systemd_fixture.py tests/test_nested_fixture_source.py tests/test_nested_fixture_continuation.py tests/test_nested_repair_health_contract.py tests/test_nested_acceptance_guard.py -q -o addopts=
  ```

  **291 passed in 17.08s**, exit 0.
- `python -m black --check scripts/deploy_probe_harness.py tests/test_deploy_probe_harness.py`
  — exit 0, 2 files unchanged.
- `python -m isort --check-only scripts/deploy_probe_harness.py tests/test_deploy_probe_harness.py`
  — exit 0.
- `python -m flake8 scripts/deploy_probe_harness.py tests/test_deploy_probe_harness.py`
  — exit 0.
- Staged `git diff --cached --check` — exit 0. Staged Python blob hashes equal
  the working LF-byte pins above. No full native core, live UI suite,
  app service, broad repair suite or actual deployment/probe was run.

Tests exercise the real archive/schema decision logic using historical bytes,
malformed header cases, duplicates, wrong raw bytes/map/root/mode/missing member,
guard refusal before effects, old support pin/cache/initializer/receipt/live guard/
origin refusal and the verified-helper return path. The portable FD model executes
the REAL extraction flow, asserts no-follow/exclusive single-component operations,
existing target file/link/directory refusal without writes, unsafe `/opt` refusal,
short writes, normalized content/modes/owners, fsync coverage and changed-parent
refusal with retained artifacts. Host transport is a spy, but exact argv, isolated
payload compilation/injection order, raw input pins, no repeated transport into
existing evidence and no nonce in receipts are checked. Origin ordering uses a spy
callback which is never called. These are offline tests, **not POSIX/runtime proof**;
the FD model substitutes the reviewed old helper's parent checks, and live guard/
systemd/venv state remain unobserved. Prior broader Windows/core/repair validation
limits in `probe-adoption-report.md` are not resolved or relabeled by this suite.

## Proposed commands — NOT executed, controller review/authorization required

From repository root, under the existing private scratch parent:

```powershell
$s = '.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance'
$pins = @('--approval-sha256', '645f294d50f33eab28bc6b19b9b213d5e01f0d325e3d94c25a74787253cecc73', '--operator-sha256', '12500f0fd8dce6b19d1a0cca17fa46588a0ad3fee7cd63dcce2bd598516945f2')
$inputs = @('--archive', "$s/probe-harness-0976f10-PENDING.tar", '--approval', "$s/probe-harness-approval-PENDING.json", '--receipt', "$s/provider-receipt.json")
python -I -B scripts/deploy_probe_harness.py @inputs @pins --evidence-dir "$s/probe-deploy-0976f10-01"
```

Only after that succeeds and its external receipt is reviewed, a separately
authorized read-only origin observation can use the same fixed inputs/pins with
**different NEW evidence**, not a deployment retry:

```powershell
python -I -B scripts/deploy_probe_harness.py @inputs @pins --origins-only --evidence-dir "$s/probe-origins-0976f10-01"
```

The controller still owns independent review of this operator, adoption of the
external approval bytes, current interpreter/venv trust and preservation evidence
for old d1/829/source trees, original receipts, installed helper/units, active UI and
protected config3354. This stage neither inspects nor modifies those live states.
The deployer has no write path to them. **ONE actual probe, NEW UUID/roots and NEW
evidence still requires its subsequent separate authorization.** No readiness,
repair, update, marker creation, application unit operation or automatic retry is
implied by either command or this report.
