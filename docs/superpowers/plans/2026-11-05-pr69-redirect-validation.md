# Per-Redirect Host Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject any untrusted or non-HTTPS redirect before urllib contacts the redirected host.

**Architecture:** Use a request-scoped `HTTPRedirectHandler` that validates each target before returning a redirected request. GitHub API requests allow only `api.github.com`; release/source downloads use the existing asset-host allowlist. Keep final-response validation as defense in depth.

**Tech Stack:** Python 3.12+, `urllib.request`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-pr69-review-followups-design.md`

## Global Constraints

- Require HTTPS for the initial URL and every redirect.
- GitHub API requests stay on `api.github.com`.
- Release/source downloads may redirect only among `_DOWNLOAD_HOSTS`.
- Add no Python dependencies and preserve response-size limits.

## Review Focus

- An untrusted intermediate hop must be rejected even if it claims it would redirect back to an allowed host.
- HTTP downgrade redirects must be rejected before following.
- Existing allowed GitHub-to-codeload and release-asset redirects must continue to work.

---

### Task 1: Validate each redirect before following it

**Files:**
- Modify: `installer/prepare_release.py`
- Test: `tests/test_prepare_release.py`

**Interfaces:**
- Add `_AllowlistedRedirectHandler(HTTPRedirectHandler)` initialized with an allowed-host set.
- Add `_open_url(request: Request, *, timeout: int, allowed_hosts: set[str])` using a request-scoped opener.
- `_download(...)` and `_github_api_json(...)` use `_open_url` with their respective allowlists.

- [x] **Step 1: Write failing redirect-handler tests**

Add `test_redirect_handler_rejects_untrusted_intermediate_host_before_following` and a downgrade case. Assert the handler raises before a redirected request is returned; preserve allowed-host redirect tests.

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_prepare_release.py -k redirect -q`
Expected: FAIL because urllib's default handler follows redirects before the current final-host check.

- [x] **Step 3: Install the request-scoped allowlist handler**

Implement `_AllowlistedRedirectHandler` and `_open_url`, use `api.github.com` for API calls and `_DOWNLOAD_HOSTS` for asset/source downloads, and retain final URL checks.

- [x] **Step 4: Run focused release tests and style checks**

Run: `pytest tests/test_prepare_release.py tests/test_release_artifacts.py -q`
Expected: all tests pass, including allowed redirects and rejection of untrusted/downgrade redirects.

- [x] **Step 5: Commit**

Use commit message: `fix: validate every release download redirect`.
