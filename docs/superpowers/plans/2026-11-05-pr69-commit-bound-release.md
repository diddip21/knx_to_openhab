# Commit-Bound Release Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject release assets unless a deterministic rebuild from the API-selected commit produces the exact downloaded archive.

**Architecture:** Fetch the selected commit's Git tree and source snapshot, verify source files against Git blob hashes, and rebuild through the shared deterministic release builder. Keep the checksum sidecar as an additional transfer-integrity check; never use it as the commit trust anchor.

**Tech Stack:** Python 3.12+, `urllib`, `tarfile`, Git object SHA-1 hashing, existing deterministic release builder, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Add no Python dependencies.
- Do not require a Git executable on the update host.
- Fail closed if the GitHub commit tree or source snapshot is missing, malformed, or truncated.
- Preserve existing archive path, size, and regular-file safety checks.
- Apply path, expansion-size, and file-type checks to the downloaded source snapshot before reading its files.
- Treat the `.sha256` sidecar as an additional corruption check, not as the trust anchor.

## Review Focus

- A replaced archive with a matching replaced sidecar must still fail commit verification (`test_prepare_release_rejects_asset_replacement_even_with_matching_checksum`).
- A valid source archive must match the selected commit's blob hashes and rebuild byte-for-byte (`test_prepare_release_accepts_archive_rebuilt_from_selected_commit`).
- A truncated or malformed Git tree must fail closed and clean temporary assets (`test_prepare_release_rejects_truncated_commit_tree`).
- GitHub source tar paths and redirects must remain bounded and restricted to HTTPS allowlisted hosts (`test_prepare_release_rejects_unsafe_commit_source_paths`, `test_prepare_release_rejects_untrusted_source_redirect`).
- Existing checksum-mismatch and unsafe-release-member rejection must continue to pass (`test_rejects_a_checksum_mismatch_without_leaving_extracted_files`, `test_rejects_unsafe_archive_paths`).

---

### Task 1: Rebuild release artifacts from an explicit commit manifest

**Files:**
- Modify: `scripts/build_release.py`
- Test: `tests/test_release_artifacts.py`

**Interfaces:**
- Extend `build_release(repo_root: Path, version: str, output_dir: Path, *, tracked_files: Iterable[tuple[PurePosixPath, int]] | None = None) -> tuple[Path, Path]`.
- When `tracked_files` is omitted, retain the current Git-index behavior. When supplied, apply the same release exclusions, sort paths, and use the supplied Git modes without invoking Git.

- [x] **Step 1: Write the failing manifest-builder test**

Add `test_build_release_with_commit_manifest_matches_git_index_build` using the existing temporary Git repository fixture. Build once from `git ls-files` and once from an explicit `(PurePosixPath, mode)` manifest; assert the `.tar.gz` bytes and `.sha256` contents are identical.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_release_artifacts.py::test_build_release_with_commit_manifest_matches_git_index_build -q`
Expected: FAIL because `build_release` does not accept an explicit manifest.

- [x] **Step 3: Add optional manifest input to the deterministic builder**

Pass the explicit list through `_write_archive` and the shared release filtering/sorting logic. Keep the CLI and normal Git-index path unchanged.

- [x] **Step 4: Run builder tests**

Run: `pytest tests/test_release_artifacts.py -q`
Expected: all release-artifact tests pass, including identical archive bytes for both inputs.

- [x] **Step 5: Commit the isolated builder change**

Use commit message: `fix: rebuild releases from an explicit commit manifest`.

### Task 2: Bind downloaded release assets to the selected commit

**Files:**
- Modify: `installer/prepare_release.py`
- Test: `tests/test_prepare_release.py`

**Interfaces:**
- Add `_fetch_commit_file_manifest(repository: str, commit_hash: str) -> list[tuple[PurePosixPath, int, str]]`; entries contain normalized path, Git mode, and Git blob SHA-1.
- Add `_verify_release_matches_commit(archive_path: Path, *, repository: str, commit_hash: str, version: str, scratch_dir: Path) -> None`.
- `prepare_release(...)` calls commit verification after downloading the archive and sidecar, but before `verify_and_extract(...)`.

- [x] **Step 1: Add failing tests for accepted and substituted assets**

Add `test_prepare_release_accepts_archive_rebuilt_from_selected_commit` and `test_prepare_release_rejects_asset_replacement_even_with_matching_checksum`. Mock GitHub API/source downloads; the second test changes a required application file and regenerates a matching sidecar. Assert rejection before any staged release files remain.

- [x] **Step 2: Add failing tests for invalid source metadata and redirects**

Add `test_prepare_release_rejects_truncated_commit_tree`, `test_prepare_release_rejects_unsafe_commit_source_paths`, and `test_prepare_release_rejects_untrusted_source_redirect`. Assert the error is actionable, no source path escapes the scratch directory, and all temporary `.assets-*` content is removed.

- [x] **Step 3: Run the new tests to verify they fail**

Run: `pytest tests/test_prepare_release.py -q`
Expected: failures because no commit tree or source snapshot is currently fetched or compared.

- [x] **Step 4: Implement commit-tree/source verification**

Fetch the Git commit object and recursive tree through HTTPS GitHub API endpoints; reject malformed entries and `truncated: true`. Download the source snapshot by the exact commit hash, add only the required HTTPS source host to `_DOWNLOAD_HOSTS`, and safely extract it into the private scratch directory while rejecting traversal paths, oversized expansion, and unsupported member types. Verify each packaged source file with `sha1(b"blob <size>\0" + content)`. Rebuild with `build_release(..., tracked_files=...)`; compare the rebuilt archive SHA-256 with the downloaded release archive. Clean the source snapshot and rebuilt files in the existing `finally` cleanup path.

- [x] **Step 5: Run focused release tests**

Run: `pytest tests/test_prepare_release.py tests/test_release_artifacts.py -q`
Expected: all focused tests pass, including existing extraction safety and checksum mismatch cases.

- [x] **Step 6: Commit the commit-binding change**

Use commit message: `fix: bind release archives to selected commits`.
