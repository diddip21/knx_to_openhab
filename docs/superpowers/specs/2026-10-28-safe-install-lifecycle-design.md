# Safe Install and Update Lifecycle — Design

## Intent

Implement the remaining install, release, migration, updater, and lifecycle-test work in Issues #19, #24–#31, excluding #38 and PR #39. The main goal is to make upgrades reproducible and reversible while keeping user configuration, secrets, jobs, and backups outside replaceable application releases.

## Goals

- Keep canonical install/config/data/backup paths from `knxoh_paths.py` and `/etc/knx_to_openhab/paths.env` as the only path contract.
- Store immutable application versions under `releases/<semver>` and activate them through an atomic `current` symlink; retain the legacy flat install as a migration source.
- Publish tagged source archives with SHA-256 checksums; default installer and updater channel is stable, with explicit prerelease channels.
- Make configuration migrations versioned, backed up, and recoverable; never mix user data into a release archive.
- Run update work outside the Web UI service lifecycle, as `knxohui`, with only exact systemd actions privileged.
- Exercise install, repeat install, upgrade, failure, rollback, uninstall, and purge on Linux CI using isolated temporary paths and mocked system services.

## Non-goals

- Do not create or publish a real GitHub release, tag, or PR during implementation.
- Do not change generated OpenHAB file behavior or touch Issue #38 / PR #39.
- Do not add an apt repository or make the running application writable by root as an update strategy.

## Approaches

1. **In-place Git update:** minimal change, but keeps code and user state in one mutable tree and cannot provide a verified immutable artifact or dependable rollback. Rejected.
2. **Versioned release archives with atomic activation (chosen):** a tag workflow publishes a source archive and checksum; install/update verifies and extracts it into a new release, then atomically switches `current`. A separate systemd update unit lets the worker survive restarting the Web UI. This uses existing Linux/systemd deployment and the current canonical paths.
3. **Package-managed install:** strong system package lifecycle, but requires hosting and maintaining a Debian repository and is a poor fit for the current GitHub-based installer. Rejected for this scope.

## Design Decisions

- Use a single SemVer `VERSION` source and tag format `v<version>`. Stable tags have no prerelease suffix; beta and release-candidate tags use SemVer prerelease identifiers and publish as GitHub prereleases.
- Produce a deterministic `knx_to_openhab-<version>.tar.gz` and adjacent SHA-256 file; installer/updater must verify the checksum before extraction.
- Keep compatibility API fields (`commit_hash`, `current_commit`, etc.) while adding semantic version/channel fields so older UI clients keep working.
- Keep external config, secrets, runtime data, and backups unchanged during ordinary uninstall. Require `--purge` plus a typed confirmation to delete them. Retain the service account in ordinary uninstall so retained files keep an owner; purge may remove it after data deletion.
- Make schema changes additive and atomic; snapshot affected config/secrets/index files before migration and restore that snapshot if migration or the release health check fails.
- Treat the GitHub Actions release workflow as automation definition only; an authorized maintainer still creates/pushes tags and publishes releases.

## Constraints

- Python 3.12+; Bash/systemd target is Debian-family Linux.
- Existing path environment and external data layout remain compatible.
- No arbitrary Git or shell commands are added to sudoers.
- Destructive cleanup is limited to validated configured paths and explicit purge confirmation.
- Verify with focused pytest tests, full applicable tests, formatting/lint, and `git diff --check`; report Linux-only checks not runnable on Windows.

## Work Units

1. Safe uninstaller (#28), first; independent and data-protective.
2. Release and lifecycle chain (#30, #24, #27, #25, #26, #19, #31), in dependency order.
3. Conservative repository inventory/cleanup (#36), last and independent.
