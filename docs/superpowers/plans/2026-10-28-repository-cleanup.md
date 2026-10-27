# Conservative Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Issue #36 with a reproducible repository inventory and only evidence-backed cleanup.

**Architecture:** Inventory tracked paths and hash-identical files, trace each candidate through Python/shell/template/docs/CI references, verify pytest collection, then make each safe removal in a separate test-backed change. Keep an audit document listing removals and deferred candidates.

**Tech Stack:** Git, Python standard library, pytest, existing lint and CI tools.

**Spec:** `docs/superpowers/specs/2026-10-28-repository-cleanup-design.md`

## Global Constraints

- No deletions based only on naming, age, or absence of direct imports.
- Do not change production behavior or supported configuration formats.
- Do not inspect or modify Issue #38 / PR #39 implementation.

## Review Focus

- Dynamic imports and script entry points: test collection and source-reference audit before removal.
- Templates and generated fixtures: compare against generator/template consumers; golden tests protect expected output.
- GitHub workflows and developer docs: retain files referenced by CI and documented commands; cross-reference scan.
- Same-content files with different paths: compare hashes and references before merging/removal; record equivalence.
- Generated/local artifacts: verify they are ignored or untracked; do not remove user data.

---

### Task 1: Inventory and classify candidates

**Files:**
- Create: `docs/REPOSITORY_INVENTORY.md`
- Test: `tests/test_repository_inventory.py`

- [ ] Add an inventory checker that lists tracked files, duplicate hashes, and test-collected modules without treating any candidate as removable by default.
- [ ] Run it and capture a baseline inventory.
- [ ] Cross-check candidates with Python imports, shell callers, templates, workflows, documentation, and test collection; record evidence and disposition.
- [ ] Run tests/lint before any deletion and save baseline results in the inventory.
- [ ] Commit: `docs: record repository cleanup inventory`.

### Task 2: Remove only proven duplicates/obsolete artifacts

**Files:**
- Modify only candidate files named by Task 1 evidence.
- Test: focused tests owning each candidate; full core suite.

- [ ] For each candidate, add/update a focused test or reference check that would fail if a live file were removed.
- [ ] Remove one candidate group at a time and run its focused test.
- [ ] Update inventory with the exact rationale and verification for every removal; defer ambiguous items.
- [ ] Run core tests, lint, and `git diff --check`; compare inventory to Issue #36 acceptance criteria.
- [ ] Commit: `chore: remove verified unused repository files`.

---
