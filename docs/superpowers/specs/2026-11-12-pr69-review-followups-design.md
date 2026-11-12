# PR #69 review follow-ups

## Intent

Address the six currently open Codex findings on PR #69 with regression coverage, preserving safe purge behavior, active-release consistency, and the pre-update recovery archive.

## Goals and constraints

- Remove a custom paths registry during purge only when it is a validated managed registry and is not already contained in a tree being deleted.
- Remove custom maintenance-lock state before deleting the `knxohui` group; never recursively delete an arbitrary lock-parent directory.
- Make `install.sh --repair` and credential recovery instructions use the active transactional release, retaining legacy behavior for non-transactional installs.
- Exclude `.git`, virtual environments, caches, and bytecode only from the application snapshot; preserve external config and runtime-data trees fully.
- Serialize scheduled backup cleanup against an active update with the existing updater lock, without weakening the maintenance lock.
- Add regression tests for each reported condition. Keep existing defaults and legacy install behavior compatible.

## Approaches considered

1. **Targeted fixes with regression tests (selected):** repair each concrete path at its source, reuse existing lock/path contracts, and preserve the legacy flow. This has the smallest behavioral surface while fixing the reported data-loss and stale-code cases.
2. **Dismiss or document the findings:** cheaper, but leaves stale setup commands, purge residue, and a race that can delete the only pre-update archive.
3. **Broader updater/uninstaller redesign:** could centralize lifecycle logic, but expands risk and is not required to resolve these reproductions.

## Design calls

- Purge cleanup must not trust an arbitrary `KNXOH_PATHS_FILE` override. Validate the registry file and its protected path before removing it; if its path is already inside the install/config/data/backup trees purged by this invocation, rely on that tree removal.
- The custom maintenance-lock parent is expected to be dedicated. Remove only the lock file and use non-recursive `rmdir`; if unrelated contents prevent removal, do not delete the service group.
- Resolve transactional `current` targets only when they resolve below the install's `releases/` directory and contain the expected setup script.
- Canonicalize the selected install/release directory before checking that setup resolves beneath it; this preserves relative path spelling such as trailing slashes and symlinked ancestors without weakening target containment.
- Treat a headerless paths registry as legacy only at `/etc/knx_to_openhab/paths.env`; custom registry paths require the installer-managed header because recognized assignment content alone is not a trust signal.
- Backup cleanup acquires the same exclusive `data/updater.lock` used by `update.sh`, while retaining its shared maintenance lock. This prevents deletion of an in-progress update's newly published archive.

## Acceptance criteria

- Tests prove a custom external managed registry is removed on purge, an invalid/arbitrary registry is not removed, and a registry under a purged tree is not separately targeted.
- Tests prove custom lock parent/file are removed before group deletion; unexpected directory contents prevent service-group deletion.
- Tests prove transactional repair and credential-recovery text point to `current`/the resolved active release, while legacy installs retain their current path.
- Tests prove external `venv`, `.git`, `__pycache__`, and `.pyc` content is preserved in backups while those artifacts remain excluded from the application snapshot.
- Tests prove backup cleanup cannot run concurrently with the updater lock holder and proceeds once that lock is released.
- Focused tests, core tests, lint, and `git diff --check` pass; all findings are dispositioned in PR threads before merge.
