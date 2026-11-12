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
- A packaging-rule change in the selected commit must use that commit's builder, not the active release's builder (`test_prepare_release_uses_selected_commit_builder_after_packaging_rule_change`).
- A truncated or malformed Git tree must fail closed and clean temporary assets (`test_prepare_release_rejects_truncated_commit_tree`).
- GitHub source tar paths and redirects must remain bounded and restricted to HTTPS allowlisted hosts (`test_prepare_release_rejects_unsafe_commit_source_paths`, `test_prepare_release_rejects_untrusted_source_redirect`).
- Excluded source files remain subject to the expanded-size limit, while excluded links are not extracted (`test_safe_extract_commit_source_counts_excluded_files_toward_size_limit`, `test_safe_extract_commit_source_ignores_symlinks_at_excluded_paths`).
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
- Add `_fetch_commit_file_manifest(repository: str, commit_hash: str) -> list[tuple[PurePosixPath, int, str]]`; entries contain normalized path, Git mode, and Git SHA-1 for regular files, links, and gitlinks. Do not apply the active release's exclusions while fetching.
- Add `_load_selected_release_builder(source_root: Path, manifest: list[tuple[PurePosixPath, int, str]], commit_hash: str) -> ModuleType`; verify all regular source blobs and the selected builder blob before loading its `is_excluded_release_path()` and `build_release(..., tracked_files=...)` functions.
- Add `_verify_release_matches_commit(archive_path: Path, *, repository: str, commit_hash: str, version: str, scratch_dir: Path) -> None`.
- `prepare_release(...)` calls commit verification after downloading the archive and sidecar, but before `verify_and_extract(...)`.

- [x] **Step 1: Add failing tests for accepted and substituted assets**

Add `test_prepare_release_accepts_archive_rebuilt_from_selected_commit` and `test_prepare_release_rejects_asset_replacement_even_with_matching_checksum`. Mock GitHub API/source downloads; the second test changes a required application file and regenerates a matching sidecar. Assert rejection before any staged release files remain.

- [x] **Step 2: Add failing tests for invalid source metadata and redirects**

Add `test_prepare_release_rejects_truncated_commit_tree`, `test_prepare_release_rejects_unsafe_commit_source_paths`, `test_prepare_release_rejects_untrusted_source_redirect`, `test_safe_extract_commit_source_ignores_symlinks_at_excluded_paths`, and `test_safe_extract_commit_source_counts_excluded_files_toward_size_limit`. Assert actionable errors, safe paths, no extraction of excluded links, and that excluded regular-member sizes count toward the expansion limit. Existing `prepare_release` integration tests assert temporary `.assets-*` cleanup.

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

### Task 3: Use packaging rules from the selected commit

**Files:**
- Modify: `installer/prepare_release.py`
- Test: `tests/test_prepare_release.py`

**Interfaces:**
- `_fetch_commit_file_manifest(...)` returns all safe non-tree Git entries, including symlinks and gitlinks; selected release rules decide whether an entry is excluded.
- `_load_selected_release_builder(...)` verifies the source snapshot's regular files against the manifest before importing the selected commit's builder.
- `_verify_release_matches_commit(...)` calls that builder's explicit-manifest API and never falls back to the active release's packaging rules.

- [x] **Step 1: Write the failing builder-version transition test**

Add `test_prepare_release_uses_selected_commit_builder_after_packaging_rule_change`. Modify the test commit's builder to exclude an additional file, build its asset with that selected rule, and assert `prepare_release()` accepts it.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_prepare_release.py::test_prepare_release_uses_selected_commit_builder_after_packaging_rule_change -q`
Expected: FAIL because verification currently imports the active checkout's builder and includes the newly excluded file.

- [x] **Step 3: Verify and load the selected builder only after authenticating source files**

Remove the active builder import, preserve all safe Git tree entries until the selected filter is known, verify all regular snapshot files and reject extras, then load the selected builder from its verified source file.

- [x] **Step 4: Rebuild using the selected commit's inclusion rules**

Filter with the selected builder's `is_excluded_release_path`, reject unsupported included entry modes, and call its explicit `tracked_files` builder interface. Fail closed on missing/incompatible functions.

- [x] **Step 5: Run focused release tests and formatting checks**

Run: `pytest tests/test_prepare_release.py tests/test_release_artifacts.py -q`
Expected: all release preparation and deterministic builder tests pass.

- [x] **Step 6: Commit the compatibility fix**

Use commit message: `fix: verify releases with selected commit builder`.
