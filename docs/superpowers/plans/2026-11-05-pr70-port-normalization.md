# PR #70 Health-Probe Port Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the update health probe accept the same numeric-string ports supported by Web UI endpoint resolution, without accepting malformed or unsafe values.

**Architecture:** Add one port-normalization helper in `installer/web_ui_endpoint.py` and use it in both endpoint resolvers. It accepts an integer or an ASCII decimal string, rejects booleans/floats/other strings, and enforces `1..65535` after conversion.

**Tech Stack:** Python 3.12+, standard library, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-pr70-review-followup-design.md`

## Global Constraints

- No new dependencies.
- Preserve configured valid ports and existing endpoint behavior.
- Accept only integer values and ASCII decimal strings; reject booleans, floats, malformed strings, and values outside `1..65535`.
- Keep Black line length at 100 and existing pytest conventions.

## Review Focus

- Numeric string `"8085"` must normalize to integer `8085` in the health endpoint (`test_health_probe_accepts_decimal_string_port`).
- Integer ports remain unchanged in both resolver paths (`test_endpoint_resolution_normalizes_string_port_consistently`).
- Booleans and floats must not be accepted as integer ports (`test_health_probe_rejects_non_integer_ports`).
- Malformed and signed/decimal strings must be rejected (`test_health_probe_rejects_malformed_port_strings`).
- Ports `0` and `65536` must fail the range check whether supplied as integers or strings (`test_health_probe_rejects_out_of_range_ports`).

---

### Task 1: Normalize ports consistently

**Files:**
- Modify: `installer/web_ui_endpoint.py`
- Test: `tests/test_web_ui_endpoint.py`

**Interfaces:**
- Produces: `_normalize_port(port: object) -> int`, shared by `resolve_web_ui_endpoint()` and `resolve_web_ui_health_endpoint()`.

- [x] **Step 1: Add failing tests**

Add the five review-focus tests. Assert that `"8085"` returns port `8085`; bool, float, malformed strings, `0`, and `65536` raise `ValueError`.

- [x] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest -q tests/test_web_ui_endpoint.py -k 'string_port or non_integer_ports or malformed_port_strings or out_of_range_ports'`

Expected: the numeric-string health-probe test fails because the current helper requires `type(port) is int`; other new invalid-input tests may expose inconsistent validation.

- [x] **Step 3: Implement `_normalize_port()`**

Reject `bool` and non-`int`/non-`str` values. For strings, require ASCII digits before converting with `int()`. Then apply the existing `1..65535` range check. Replace the independent conversions/checks in both resolver functions with this helper.

- [x] **Step 4: Run the full endpoint tests**

Run: `python -m pytest -q tests/test_web_ui_endpoint.py`

Expected: all endpoint tests pass.

- [x] **Step 5: Commit**

```bash
git add installer/web_ui_endpoint.py tests/test_web_ui_endpoint.py
git commit -m "fix: normalize Web UI health probe ports"
```
