# PAX Expansion-Limit Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the source archive's expanded-size limit before tar parsing can materialize uncounted PAX metadata.

**Architecture:** Bounded gzip decompression writes to a private temporary tar file. `tarfile` then reads the bounded uncompressed file, preserving the existing member validation and extraction logic.

**Tech Stack:** Python 3.12+, `gzip`, `tempfile`, `tarfile`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-pax-expansion-limit.md`

## Global Constraints

- Keep dependencies unchanged.
- Keep the existing compressed-download and regular-file expanded-size limits.
- Fail closed using `ReleasePreparationError` for malformed, truncated, or over-limit source archives.

## Review Focus

- PAX metadata is counted before parsing — test a tiny compressed archive with a large PAX field and no oversized regular file, using a baseline tar as the limit.
- Exact-limit streams remain accepted while one-byte-over streams fail — assert the PAX archive succeeds at its exact raw tar length and fails one byte below.
- Truncated/corrupt gzip trailers do not escape the documented error type — include this regression in the initial red test step.
- Failure closes temporary resources — after a rejected extraction, remove its scratch tree and confirm cleanup succeeds.
- Existing tar safety checks remain unchanged — run all `tests/test_prepare_release.py` tests.

---

### Task 1: Bound total decompressed source bytes

**Files:**
- Modify: `installer/prepare_release.py:_safe_extract_commit_source`
- Test: `tests/test_prepare_release.py`

**Interfaces:**
- Consumes: `_EXPANDED_LIMIT`, `_CHUNK_SIZE`, and `ReleasePreparationError`.
- Produces: the existing `_safe_extract_commit_source(source_archive, scratch_dir)` behavior with a bound applied before `tarfile` iteration.

- [x] **Step 1: Add PAX, boundary, and truncated-gzip regressions**

Create baseline and PAX gzip tar fixtures; verify the PAX archive is rejected at the baseline uncompressed tar length despite having no oversized regular file, accepted at its exact raw tar length, and rejected one byte below that length. Add a truncated-gzip case that requires `ReleasePreparationError` and verify failed scratch data can be removed.

- [x] **Step 2: Run the regression and verify it fails on current behavior**

Run: `pytest tests/test_prepare_release.py::test_safe_extract_commit_source_counts_pax_metadata_toward_size_limit tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_truncated_gzip -q`

Expected: FAIL because the current extractor accepts the PAX archive.

- [x] **Step 3: Add bounded, chunked gzip expansion before tar parsing**

Write at most `_EXPANDED_LIMIT` decompressed bytes to a private temporary file; reject the first byte beyond the limit, rewind, and open the raw tar from that file. Normalize gzip/I/O/tar errors into `ReleasePreparationError` without swallowing the explicit size-limit error.

- [x] **Step 4: Run extraction tests**

Run: `pytest tests/test_prepare_release.py -q`

Expected: all tests pass, including PAX-limit, boundary, and malformed-stream regressions.

- [x] **Step 5: Verify and commit**

Run: `black --check installer/prepare_release.py tests/test_prepare_release.py && isort --check-only installer/prepare_release.py tests/test_prepare_release.py && flake8 installer/prepare_release.py tests/test_prepare_release.py && git diff --check`

Commit: `fix: count tar metadata toward source expansion limit`.
