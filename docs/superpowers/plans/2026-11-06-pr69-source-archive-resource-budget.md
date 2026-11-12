# Source Archive Resource-Budget Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound source archive disk and parser memory use without reducing the existing 1-GiB extracted-source limit.

**Architecture:** Preflight the compressed tar in bounded streaming passes without writing a decompressed copy. During preflight, use `tarfile` streaming mode with a `TarInfo` subclass that rejects oversized PAX/GNU extended records before their bodies are read; drain the gzip stream to enforce total decompressed size and validate integrity. Extract by reopening the original gzip in streaming mode.

**Tech Stack:** Python 3.12+, gzip, tarfile, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-pr69-source-archive-resource-budget-design.md`

## Global Constraints

- Keep dependencies unchanged and `_EXPANDED_LIMIT` at 1 GiB.
- Do not store a decompressed archive or materialize the full stream in memory.
- Bound PAX/global-PAX/GNU long-name/long-link records to 1 MiB before their bodies are read.
- Bound cumulative pending local PAX headers, consecutive nested extended-header depth (64), archive member count (100,000), and cumulative UTF-8 path bytes (16 MiB).
- Preserve safe extraction, commit verification, and gzip integrity checks.

## Review Focus

- Total decompressed size and gzip trailer are validated before extraction — test exact boundary, over-limit PAX, and truncation.
- No full decompressed temp archive remains — assert the extraction path does not create one.
- `tarfile` never receives an oversized PAX or GNU long-name body — test each extended-header type over 1 MiB.
- Ordinary PAX metadata and regular member data continue to extract correctly — run the full release-preparation test file.
- Malformed tar headers fail closed rather than causing unbounded skipping — test a bad header/size encoding if scanner behavior requires it.
- Consecutive local/global PAX and GNU long-name/link chains are rejected before `RecursionError` — exercise all four types.

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

- [x] **Step 1: Add oversized PAX and GNU long-name regressions**

Create valid compressed tar fixtures with each metadata record larger than 1 MiB but below `_EXPANDED_LIMIT`; assert extraction raises `ReleasePreparationError` before yielding any member.

- [x] **Step 2: Run the new tests and verify current behavior accepts the records**

Run: `pytest tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_oversized_pax_record tests/test_prepare_release.py::test_safe_extract_commit_source_rejects_oversized_gnu_long_name -q`

Expected: FAIL because the current standard-library parser accepts/materializes these in-limit records.

- [x] **Step 3: Guard extended-header sizes during preflight**

Use a `TarInfo` subclass to check PAX/global-PAX/GNU long-name/long-link metadata sizes before calling the standard parser methods that read their bodies. Run tarfile in streaming mode over a bounded gzip reader; drain all remaining decompressed bytes through EOF so total size and CRC/trailer validation remain complete. This keeps PAX size overrides and sparse offsets aligned according to the standard parser.

- [x] **Step 4: Run all release-preparation tests and static checks**

Run: `pytest tests/test_prepare_release.py -q`

Run: `black --check installer/prepare_release.py tests/test_prepare_release.py && isort --check-only installer/prepare_release.py tests/test_prepare_release.py && flake8 installer/prepare_release.py tests/test_prepare_release.py && git diff --check`

Expected: all tests and checks pass.

- [x] **Step 5: Commit**

Commit: `fix: bound source tar extended metadata records`.

### Review follow-up: cumulative global PAX metadata

- RED: two individually valid 93-byte global PAX records passed a 128-byte cumulative metadata budget.
- GREEN: `_BoundedMetadataTarInfo` counts global PAX record bodies before `tarfile` reads them, and source extraction uses the same bounded parser as preflight.
- Verification: `pytest tests/test_prepare_release.py -q` → 41 passed.

### Review follow-up: malformed tar headers

- RED: after a valid root member, both an invalid checksum and an invalid octal size field were silently accepted because `TarFile.next()` treated the resulting `HeaderError` as end-of-archive.
- GREEN: `_BoundedMetadataTarInfo._fromtarfile()` propagates malformed/truncated header errors as `ReleasePreparationError` while preserving zero-block end markers.
- Verification: `pytest tests/test_prepare_release.py -q` → 43 passed.

### Review follow-up: scratch disk peak before final extraction

- RED: the integration regression observed `source/` still present when `verify_and_extract()` began.
- GREEN: after a successful deterministic digest comparison, `_verify_release_matches_commit()` removes both `source/` and `rebuilt/`; cleanup errors abort before final extraction.
- Verification: `pytest tests/test_prepare_release.py -q` → 43 passed.

### Review follow-up: cumulative local metadata and entry budgets

- RED: two individually valid 93-byte local PAX records passed a 128-byte pending-metadata budget; independent regressions also showed no preflight member/path budget and no limit during release extraction.
- GREEN: `_BoundedMetadataTarInfo` bounds nested local PAX body bytes before reads; preflight and both extraction paths cap yielded members at 100,000 and cumulative UTF-8 member-path bytes at 16 MiB.
- Verification: `pytest tests/test_prepare_release.py -q` → 47 passed.

### Review follow-up: cap nested extended-header recursion

- RED: chains of 1,100 tiny local/global PAX or GNU long-name/link headers escaped byte budgets and raised an uncaught `RecursionError` during preflight.
- GREEN: the shared `TarInfo` hooks cap nested extended-header depth at 64 for PAX and GNU long headers; preflight also normalizes any residual `RecursionError` into `ReleasePreparationError`.
- Verification: `pytest tests/test_prepare_release.py -q` → 52 passed.
