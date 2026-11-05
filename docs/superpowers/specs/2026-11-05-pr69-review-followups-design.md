# PR #69 review follow-ups design

## Intent

Close the five actionable findings from the final review of PR #69 while
preserving transactional release updates and their recovery behavior. The
security goal is to ensure that release assets cannot substitute code for the
commit selected through the GitHub API.

## Scope and goals

- Bind the downloaded release archive to the selected commit before extraction,
dependency installation, or activation.
- Keep the existing `.sha256` check as a transfer-integrity check, not as the
  trust anchor.
- Fix recovery guidance to use the active release, normalize saved rollback
  targets, stop an updater that is still activating during uninstall, and
  reject invalid metadata before publishing an update request.
- Add focused regression tests for all five findings and retain existing
  checksum, extraction, rollback, and update-request behavior.

## Non-goals

- Redesign release selection, the systemd updater, or the release layout.
- Add signing keys, a new artifact-attestation service, or new Python
  dependencies.
- Change legacy Git checkout update behavior beyond using the same active-path
  recovery instructions where applicable.

## Approaches

1. **Rebuild from the selected commit (selected).** Obtain the source snapshot
   for the exact API-selected commit, verify its files against that commit's
   Git tree, rebuild the release archive deterministically, and compare it to
   the downloaded asset before accepting it. This reuses the repository's
   existing deterministic release format and avoids requiring a Git executable
   on installations. It adds a source download and GitHub tree lookup, and the
   packaging rules must remain shared with `scripts/build_release.py`.
2. **Signed artifact attestation.** Attest the release archive in the workflow
   and verify its provenance during updates. This avoids rebuilding on the
   target, but introduces signing/attestation workflow and verifier
   dependencies that the project does not currently have.

A sidecar-only change is insufficient: an attacker able to replace both
release assets can create a matching checksum.

## Design calls

- Use the exact `commit_hash` already selected by the updater. Query its Git
  tree through the GitHub API; fail closed if the response is truncated,
  malformed, or unavailable.
- Download the source snapshot for that hash over HTTPS and verify each
  included file against the corresponding Git blob hash and mode from the
  selected commit tree. Reuse the release builder's inclusion/exclusion rules
  and deterministic archive writer from that selected commit rather than the
  currently active release. Verify the selected builder's Git blob before
  loading it, and fail closed if it lacks the explicit-manifest interface.
  Enforce the expanded-size limit across all regular source archive members,
  including excluded files, while never extracting source links.
- Compare the rebuilt archive digest with the downloaded release archive
  before extraction. The `.sha256` sidecar remains an additional corruption
  check. Do not fall back to accepting an asset when commit verification fails.
- Preserve current archive path, size, and regular-file safety checks. Treat
  GitHub's selected commit/tree as the trust source; this addresses substituted
  release assets, not a compromised repository commit or GitHub account.
- Use `$APP_DIR` for recovery commands that invoke installer scripts, so
  transactional installs use the active release and legacy installs continue
  to use `$INSTALL_DIR` through the existing fallback.
- Persist release rollback targets only in the validated, install-relative
  `releases/...` form. Preserve the existing `legacy` marker for legacy
  rollback.
- During uninstall, stop the Web UI before the updater so it cannot start a new
  update during teardown. Detect and stop an updater in `activating` as well as
  `active`, also cancel queued start jobs while `ActiveState=inactive`, and
  wait until no updater job remains before removing application or unit files.
  Distinguish `LoadState=not-found` from a loaded inactive unit so genuinely
  absent units remain idempotent; abort on inspection errors or unknown state.
- Apply the worker's control-character policy to commit message and author
  metadata before writing or publishing an update request. Invalid metadata
  must leave no pending request behind.
- Verify the selected builder's archive payload independently of gzip/zlib
  implementation by comparing the decompressed deterministic tar stream; keep
  the release `.sha256` check over the downloaded compressed bytes.
- Validate every HTTPS redirect target before following it. GitHub API requests
  remain on `api.github.com`; release/source downloads may redirect only among
  the existing allowlisted GitHub asset hosts.
- Print copy-paste-safe recovery commands for supported install paths containing
  whitespace by shell-escaping the complete setup-script path.

## Acceptance criteria

- A substituted archive paired with a matching substituted sidecar is rejected
  when its contents do not match the selected commit; no release code is
  extracted or activated.
- A valid deterministic release for the selected commit verifies successfully,
  including when the installed release has no `.git` directory and the host
  does not need Git installed.
- Missing or incomplete commit-tree/source data fails safely with an actionable
  error and cleans temporary files.
- Recovery messages resolve installer scripts from the active release; absolute
  `current` links produce a valid relative rollback marker.
- Uninstall stops the Web UI before its final updater check, cancels queued
  updater starts, waits for the unit and its jobs to stop, tolerates a
  `LoadState=not-found` unit, and only then deletes files.
- Control characters are rejected before request publication, and the worker
  and Web UI apply the same policy.
- Recompressing the same selected-commit tar payload with a different gzip
  compression level does not block a valid update, while changing its tar
  contents still fails verification.
- An HTTP redirect to an untrusted intermediate host is rejected before that
  host is contacted, even if the redirect chain would later return to an
  allowlisted host.
- Recovery guidance for an installation path containing spaces can be copied
  into a shell and invokes the correct active `installer/setup.sh` path.
- Focused tests, full core tests, lint/format checks, UI tests as applicable,
  and `git diff --check` pass before the PR is considered ready for review.
