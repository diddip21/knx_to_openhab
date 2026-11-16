# Release Compression Portability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept a valid selected-commit release whose gzip stream differs while its deterministic tar payload is identical.

**Architecture:** Keep the published `.sha256` validation over the downloaded compressed bytes, but compare SHA-256 digests of the decompressed tar streams when binding the asset to the selected commit. Stream both files to retain bounded memory usage.

**Tech Stack:** Python 3.12+, `gzip`, `hashlib`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Keep the existing `.sha256` check as a transfer-integrity check, not as the commit trust anchor.
- Preserve release download and expanded-size limits.
- Add no Python dependencies.
- Fail closed on invalid or truncated gzip streams and on any changed decompressed tar byte.

## Review Focus

- Different gzip compression levels must not reject identical tar payloads.
- Any changed tar header, member, or content must still fail commit verification.
- Invalid gzip data must fail closed and clean temporary staging assets.

---

### Task 1: Compare decompressed release payloads

**Files:**
- Modify: `installer/prepare_release.py`
- Test: `tests/test_prepare_release.py`

**Interfaces:**
- Add `_decompressed_archive_digest(path: Path) -> str`, streaming the decompressed bytes into SHA-256.
- `_verify_release_matches_commit(...)` compares this digest for the selected-builder output and downloaded asset. `_verify_checksum(...)` continues hashing compressed bytes.

- [x] **Step 1: Write the failing recompression test**

Add `test_prepare_release_accepts_archive_recompressed_with_different_gzip_level`. Recompress the selected commit's tar stream at a different gzip level, write a matching compressed-byte checksum sidecar, and assert `prepare_release()` accepts it.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_prepare_release.py::test_prepare_release_accepts_archive_recompressed_with_different_gzip_level -q`
Expected: FAIL because current verification compares compressed archive digests.

- [x] **Step 3: Compare decompressed tar streams**

Implement `_decompressed_archive_digest` with chunked reads and clear fail-closed handling for gzip/zlib errors. Keep checksum verification unchanged.

- [x] **Step 4: Run focused release tests and style checks**

Run: `pytest tests/test_prepare_release.py tests/test_release_artifacts.py -q`
Expected: all release preparation and builder tests pass, including substituted-asset rejection.

- [x] **Step 5: Commit**

Use commit message: `fix: compare release tar payload across gzip versions`.
