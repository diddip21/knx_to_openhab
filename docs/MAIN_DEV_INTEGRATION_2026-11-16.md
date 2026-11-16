# Main/dev integration review, 16 November 2026

This integration starts from `dev` at
`ba5732a` and preserves its 46 commits that were absent from `main`.
It uses a merge commit, without reset, force-push, rebase or squash.
PR #110 is a conflict demonstration only: its head is `main` and must not
receive conflict-resolution commits. PR #109 must land on `main` first.

## Conflict decisions

| File | Resolution and reason |
| --- | --- |
| `README.md` | Keep main's explicit legacy/YAML default and deployment explanation, together with dev's documentation and screenshot cleanup. |
| `docs/PRODUCTION_GUIDE.md` | Keep dev's verified MIT license link. |
| `docs/RELEASING.md` | Keep main's implemented transactional update/rollback description and dev's moving-branch test procedure. Preserve the version API and changelog guidance; do not describe merged updater work as future work. |
| `install.sh` | Keep main's staged installation, repair validation and safe filesystem-specific venv probe. Retain dev's bounded GitHub connectivity preflight before release lookup or package changes. Python 3.11+ and the 1 GiB floor remain required. |
| `tests/test_installer_preflight.py` | Keep main's safe-probe tests. Retain dev's host/network tests separately; its old TMPDIR-based venv probe tests are superseded by main's filesystem/ownership-aware probe tests. |
| `tests/test_privilege_policy.py` | Keep main's transactional updater tests, including dependency and health-check failures; do not restore dev's obsolete in-place Git/pip updater fixtures. Preserve unrelated dev fixes. |
| `tests/test_uninstall_modes.py` | Combine main's maintenance/quiesce/unit helpers with dev's explicit POSIX skip and optional pty import. |
| `update.sh` | Keep main's transactional activation, verified backup, interrupted-update recovery and rollback. Dev's direct checkout and in-place dependency rollback were replaced by that architecture. |
| `web_ui/backend/updater.py` | Keep main's durable request/worker protocol. Preserve dev's helpful 404/no-stable-release error and unrelated cleanup. |

## Automatically merged areas that also require review

- Keep the exact trusted `main` CI definition after #109: Python
  3.11/3.12/3.13, read-only token, root-owned lock checks, separate unprivileged
  filesystem tests and dev's screenshot/video/trace options.
- Preserve dev's audit, approved historical document removals, synthetic
  screenshots, emulator journey, UI marker scoping and release exclusions.
- Preserve main's distinction between stable install/config paths and active
  release code paths in jobs/storage. These are needed by transactional releases.
- Keep both the release manifest support from main and dev's exclusion of
  agent instructions, internal planning documents and cleanup inventories.
- This integration does not implement HomeKit #89, alter the generator's
  three-pass algorithm, release a version or create a release tag.

## Validation and subsequent gates

Validation results belong to the integration PR's current head and CI runs.
Required: formatting/lint/type checks, core tests, UI tests, clean diff,
`main` ancestry and ancestry of the original `dev` tip.

After the integration is reviewed and merged, recheck `main` ancestry in `dev`,
close #110 and retarget #108 to `dev`. Its changed diff and new CI must be
reviewed again. HomeKit's real save/reload, screenshots and legacy/YAML checks
are separate from this branch integration. The owner confirmed on 16 November
2026 that no KNX hardware test has been performed; that remains an open
HomeKit merge gate. Release approval remains a separate `dev` to `main` PR
with VERSION, changelog and annotated tag checks.
