# Runner-only repair progress

Plan: `plans/2026-10-30-installed-component-repair.md`; BASE `36415bc`.
Replacement executor preserves prior design/plan/tests. No guest commands authorized.

- Read exact blocked checkpoint and production interfaces. Other agent owns all
  production changes; no changes/staging of those paths.
- RED: `python -m pytest -q tests/test_nested_fixture_repair.py -o addopts=
  --tb=short -p no:cacheprovider` -> **9 failed, 4 errors in 0.49s**: missing repair
  module and unsupported explicit phase. This is the expected missing API boundary.
- Ruling: checkpoint embeds original complete source approval; source approval CLI
  selects only future reviewed source. Old file-map digest is frozen from existing
  retained 47e2c3a manifest, not learned from guest observations. No auto-exporter.
- Ruling: execute inline in specifically assigned existing workrepo; no worktree,
  subagents, full native core suite or guest effects, per controller constraints.
- Independent controller production and runner review still required before repair.

## Implementation checkpoint (offline only)

- Explicit repair phase, pinned checkpoint/source schema, streamed protected tree
  inventory, exact original source/component validation, retained lease, install-only
  transition, preservation/retained-bundle checks and real activation path implemented.
- Initial GREEN: focused repair plus four existing runner files **195 passed in
  1.04s**. Expanded inventory/offline-file/source cases later **234 passed in 3.60s**.
- Extra RED: activated recovery failure was not independently checked after normal
  production activation: **1 failed, 66 passed in 2.59s**. Added explicit actual
  recovery/result and queued-job checks before HTTP health; same suite green below.
- Intermediate schema tests exposed Windows path lexical handling; use POSIX paths
  for approval/inventory validation, native Paths only for real guest filesystem I/O.
  Also keep manager state in under-lock preservation equality (not just disk state).
- Initial isort check caught test import order; fixed. Final checks still pending.
- Source preparation constraint: BASE `36415bc` already contains unrelated harness
  changes vs old `47e2c3a`. A manifest of the whole later workrepo commit will
  deliberately refuse. Prepare/review a separate immutable production commit based
  on old production with only the allowed renderer/regression delta. Do not silently
  expand the allowlist. Production agent has separately committed `49dd676` here;
  this runner has not staged, modified or reviewed its production files.

## Final offline verification and review boundary

- Latest full focused command (the five repair/fixture/source/continuation/provider
  test files, `-o addopts= --tb=short -p no:cacheprovider`): **240 passed in 3.81s**.
- Latest Black `--check`: five files unchanged, exit 0. isort `--check-only`,
  flake8 and `git diff --check`: exit 0 (Git prints native LF/CRLF warnings only).
- Added RED for unknown generated-output adoption: **1 failed, 1 passed,
  70 deselected in 0.63s**; now fixed exact output paths/content/owner/mode.
- Added RED for an unguarded direct Windows inventory call: **1 failed,
  72 deselected in 0.36s**; now refuses non-POSIX/non-root before any inventory read.
- Author self-review only: checked exact allowlist/source delta, repeated locked
  preconditions, original inode lease, no existing-venv execution, retained bundle
  equality, secret-safe failure output and lease release before activation. This
  is NOT independent approval. No subagents spawned; controller owns both reviews.
- No guest effects, snapshot collection, immutable deployment or runtime repair.
  No full native core, Linux core, live systemd/WSL, browser/UI or reboot tests run.
  Task 5 and all original blocked runtime acceptance obligations remain incomplete.
