# Installed-component repair implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; no subagents.

**Goal:** Add an offline-tested, explicit guarded repair route without guest effects.
**Architecture:** Separate repair module owns exact frozen inventory and transition;
existing runner transports trusted code and pinned inputs through current guards.
**Tech Stack:** Python standard library, pytest, existing secure_fs/admin lease.
**Spec:** `docs/superpowers/2026-10-30-installed-component-repair-design.md`.

## Global constraints

- No production bootstrap/unit-test edits; preserve other agent work.
- No WSL/manager commands, deployment or runtime effects before both code reviews.
- No snapshot auto-enrollment, force, bootstrap or after-sudo fallback.
- Hash-only private checkpoints; immutable initial 3354 entries and external state.

## Review focus

- Complete allowlist vs an unknown installation: exact equality plus old-source checks.
- Under-lock races: repeat all preconditions before install_components.
- Production source drift: strict new identity and limited old/new file delta.
- Partial installation: retained evidence, no blind retry or checkpoint replacement.
- Activation failure: unlock first, stop own writers, retain actual failed state.

## Task 1: Frozen repair boundary and transition

Files: create `scripts/nested_fixture_repair.py`,
`tests/test_nested_fixture_repair.py`; modify existing fixture/runner dispatch only.

- [x] Write portable tests for exact/mismatched snapshot, source schema/delta,
  pre-effect refusals, repeated validation, preserved state and activation failure.
- [x] Run focused pytest with addopts cleared; record missing API RED.
- [x] Implement strict snapshot validation, no-follow recursive inventory,
  old/new component validation and root-held-lock install-only transition.
- [x] Add explicit `repair-environmentfile` CLI/guest/fixture dispatch requiring
  checkpoint/source files, SHA pins and full reviewed future commit.
- [x] Run focused repair plus existing runner suites; inspect RED/GREEN evidence.
- [x] Run Black/isort/flake8 on own changed Python files, git diff --check.
- [x] Commit only own runner/tests/design/plan/docs; record commit/results in ignored
  acceptance report. Leave all real-systemd obligations unclaimed and runtime blocked.
