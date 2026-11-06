# Source Archive Resource-Budget Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound source archive disk and parser memory use without reducing the existing 1-GiB extracted-source limit.

**Architecture:** Preflight the compressed tar in bounded streaming passes without writing a decompressed copy. First enforce total decompressed size and gzip integrity; then make the preflight tar-block-aware to reject oversized PAX/GNU extended records before `tarfile` parses them. Extract by reopening the original gzip in streaming mode.

**Tech Stack:** Python 3.12+, gzip, tarfile, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-source-archive-resource-budget-design.md`

## Global Constraints

- Keep dependencies unchanged and `_EXPANDED_LIMIT` at 1 GiB.
- Do not store a decompressed archive or materialize the full stream in memory.
- Bound PAX/global-PAX/GNU long-name/long-link records to 1 MiB.
- Preserve safe extraction, commit verification, and gzip integrity checks.

## Review Focus

- Total decompressed size and gzip trailer are validated before extraction — test exact boundary, over-limit PAX, and truncation.
- No full decompressed temp archive remains — assert the extraction path does not create one.
- `tarfile` never receives an oversized PAX or GNU long-name body — test each extended-header type over 1 MiB.
- Ordinary PAX metadata and regular member data continue to extract correctly — run the full release-preparation test file.
- Malformed tar headers fail closed rather than causing unbounded skipping — test a bad header/size encoding if scanner behavior requires it.

---

### Task 1: Replace decompressed tar staging with bounded preflight streaming

**Files:**
- Modify: `installer/prepare_release.py:_safe_extract_commit_source`
- Modify: `tests/test_prepare_release.py`

**Interfaces:**
- Consumes: `_EXPANDED_LIMIT`, `_CHUNK_SIZE`, and `ReleasePreparationError`.
- Produces: bounded preflight of the full gzip stream followed by safe extraction from `tarfile.open(..., mode="r|gz")`, without a decompressed temporary archive.

- [x] **Step 1: Add regressions for no-temp streaming and total-limit/trailer behavior**

Assert the source archive can be extracted without calling `tempfile.TemporaryFile`; retain the exact-limit/PAX-over-limit and truncated-gzip tests.

- [x] **Step 2: Run the regressions and verify current staging fails**

Run: `pytest tests/test_prepare_release.py::test_safe_extract_commit_source_streams_without_decompressed_temp tests/test_prepare_release.py::test_safe_extract_commit_source_counts_pax_metadata_toward_size_limit tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_truncated_gzip -q`

Expected: the no-temp test fails because the current implementation stages the raw tar.

- [x] **Step 3: Implement bounded full-stream preflight and streaming extraction**

Consume the complete gzip stream in `_CHUNK_SIZE` chunks, reject output above `_EXPANDED_LIMIT`, normalize gzip truncation/corruption, then reopen as streaming tar and retain member validation/accounting. Do not create a decompressed temporary file.

- [x] **Step 4: Run all release-preparation tests**

Run: `pytest tests/test_prepare_release.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

Commit: `fix: stream source archive preflight without temp tar`.

### Task 2: Cap tar metadata before `tarfile` materializes it

**Files:**
- Modify: `installer/prepare_release.py` preflight scanner
- Modify: `tests/test_prepare_release.py`

**Interfaces:**
- Consumes: Task 1's bounded source-archive preflight.
- Produces: a tar-block scanner that rejects PAX, global PAX, GNU long-name, or GNU long-link records above 1 MiB before normal `tarfile` parsing.

- [ ] **Step 1: Add oversized PAX and GNU long-name regressions**

Create valid compressed tar fixtures with each metadata record larger than 1 MiB but below `_EXPANDED_LIMIT`; assert extraction raises `ReleasePreparationError` before yielding any member.

- [ ] **Step 2: Run the new tests and verify current behavior accepts the records**

Run: `pytest tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_oversized_pax_record tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_oversized_gnu_long_name -q`

Expected: FAIL because the current standard-library parser accepts/materializes these in-limit records.

- [ ] **Step 3: Scan tar headers during preflight and enforce the 1-MiB metadata cap**

Use fixed-size 512-byte header reads, validate headers with `tarfile.TarInfo.frombuf`, skip member data in bounded chunks, and inspect only the header type/size for the four metadata types. Continue counting/draining the gzip stream through EOF so CRC/trailer validation remains complete.

- [ ] **Step 4: Run all release-preparation tests and static checks**

Run: `pytest tests/test_prepare_release.py -q`

Run: `black --check installer/prepare_release.py tests/test_prepare_release.py && isort --check-only installer/prepare_release.py tests/test_prepare_release.py && flake8 installer/prepare_release.py tests/test_prepare_release.py && git diff --check`

Expected: all tests and checks pass.

- [ ] **Step 5: Commit**

Commit: `fix: bound source tar extended metadata records`.
