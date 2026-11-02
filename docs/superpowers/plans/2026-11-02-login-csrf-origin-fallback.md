# Login CSRF Origin Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow login through a relay that drops only the login CSRF cookie, while retaining a signed, time-limited token and strict public-origin validation.

**Architecture:** Preserve the existing cookie/form double-submit check. Add an opt-in fallback for a missing cookie that validates the signed form token and compares the browser `Origin` (or, only if absent, the `Referer` origin) against a configured exact-origin allowlist. Mark login responses non-cacheable; do not alter authenticated session cookies or API CSRF checks.

**Tech Stack:** Python 3.12+, Flask, itsdangerous, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-login-csrf-origin-fallback-design.md`

## Global Constraints

- The normal cookie-based flow remains the default.
- The fallback applies only to `POST /login` and is enabled only for explicitly configured public origins.
- Always require a valid signed form token no older than 600 seconds.
- Do not derive trusted origins from arbitrary `Host` or forwarded headers.
- Do not change authenticated-session CSRF validation, password verification, rate limits, or session-cookie flags.
- If the relay drops `knx_session` or `knx_csrf`, this change alone will not complete sign-in.

## Review Focus

- Unlisted or cross-site `Origin` with no login CSRF cookie must fail before credential verification — test in Task 1.
- `Origin: null`, malformed `Origin`, or an absent origin and referer must fail closed — test in Task 1.
- Expired or tampered signed form tokens must fail even with an allowed origin — test in Task 1.
- A present but mismatched CSRF cookie must not use the origin fallback — test in Task 1.
- An empty/default allowlist must preserve existing behavior, and login responses must not be cached — test in Task 1.
- Malformed configured origin entries must never become trusted origins — test in Task 1.

---

### Task 1: Add the opt-in login CSRF origin fallback

**Files:**
- Modify: `web_ui/backend/storage.py` — add the empty-by-default `login_csrf_allowed_origins` configuration value and validate its shape.
- Modify: `web_ui/backend/app.py` — validate/canonicalize configured origins, perform strict request-origin matching, keep the cookie-backed check, and set login responses to `Cache-Control: no-store`.
- Test: `tests/test_password_auth.py` — cover allowlisted and rejected login requests, token validity, default compatibility, and cache headers.
- Modify: `installer/README.md` — document the setting and show the relay-origin JSON example.

**Interfaces:**
- Consumes: existing `_login_csrf_serializer()` signed tokens, `cfg`, and Flask `request`.
- Produces: optional config key `login_csrf_allowed_origins: list[str]`; missing key means `[]` and disables the fallback.

- [ ] **Step 1: Add failing tests for fallback and fail-closed cases**

  In `tests/test_password_auth.py`, add tests proving:
  - a valid token with no CSRF cookie succeeds only with an exact configured `Origin` and still issues `knx_session`/`knx_csrf` only after password verification;
  - when `Origin` is absent, an exact configured `Referer` origin is accepted;
  - absent, `null`, malformed, and unlisted origins fail before password verification;
  - a present mismatched cookie, tampered token, and expired token are rejected;
  - malformed configured origins do not authorize the fallback;
  - an empty allowlist preserves the existing missing-cookie rejection;
  - every `/login` response, including successful, already-authenticated, and auth-disabled redirects, includes `Cache-Control: no-store`.

- [ ] **Step 2: Run the focused tests and confirm the new cases fail**

  Run: `pytest tests/test_password_auth.py -q`
  Expected: the new fallback and cache-header assertions fail; existing auth tests remain green.

- [ ] **Step 3: Implement configuration and exact-origin validation**

  Add `login_csrf_allowed_origins: []` to `storage.load_config()`. Reject a non-list or non-string entries as invalid configuration. In `app.py`, parse configured values as origin-only HTTP(S) URLs (no userinfo, path, query, or fragment); malformed entries must fail closed and never authorize a request. Compare normalized `(scheme, hostname, effective port)` tuples. For request headers, parse `Origin` as an origin; use `Referer` only when the `Origin` header is absent, and compare only its parsed origin. Never use request host/forwarded-host values to construct the allowlist.

- [ ] **Step 4: Implement the login-only fallback and no-store response header**

  Keep `_valid_login_csrf()` requiring a valid token age/signature in all cases. If the cookie exists, require its constant-time match to the form token and reject mismatches. If it is absent, allow only a configured exact-origin match. Set `Cache-Control: no-store` on every `/login` response, including success, already-authenticated, and auth-disabled redirects; keep issuing the current cookie.

- [ ] **Step 5: Document configuration and run focused tests**

  Document the setting in `installer/README.md`, using `https://mcrelay.greiner-wue.de` as an example and stating that the post-login `knx_session` and `knx_csrf` cookies must still pass through the relay.

  Run: `pytest tests/test_password_auth.py -q`
  Expected: all focused auth tests pass.

- [ ] **Step 6: Run repository verification**

  Run: `pytest -q`
  Expected: all core tests pass.

  Run: `black --check web_ui/backend/app.py web_ui/backend/storage.py tests/test_password_auth.py`
  Expected: no formatting changes required.

  Run: `isort --check-only web_ui/backend/app.py web_ui/backend/storage.py tests/test_password_auth.py`
  Expected: imports are sorted.

  Run: `git diff --check`
  Expected: no whitespace errors.

- [ ] **Step 7: Manually validate through the relay after deployment**

  Configure the exact public origin, deploy, and test in the browser. Confirm login succeeds and that the browser receives `knx_session` and `knx_csrf` after successful authentication. If those cookies are still absent, stop: the relay must be fixed; do not weaken session-cookie protections.
