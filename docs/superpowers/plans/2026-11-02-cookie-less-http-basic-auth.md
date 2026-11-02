# Cookie-less HTTP Basic Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in HTTP Basic authentication mode so the Web UI works through relays that strip cookies.

**Architecture:** Keep cookie sessions as the default. In Basic mode, challenge protected requests with HTTP Basic, verify the configured credentials per request, and replace cookie-based unsafe-method CSRF validation with strict allowed-Origin validation. Do not issue session or CSRF cookies in Basic mode.

**Tech Stack:** Python 3.12+, Flask, pytest; existing `itsdangerous` session support and password hash verification.

**Spec:** `docs/superpowers/specs/2026-11-02-cookie-less-http-basic-auth-design.md`

## Global Constraints

- Existing installations remain in session mode unless explicitly configured otherwise.
- Never accept credentials in query strings or log `Authorization` values.
- Basic mode requires HTTPS in deployment and an exact origin allowlist for unsafe requests; absent/malformed/unlisted origins fail closed.
- Preserve password verification, rate limiting, static assets, public health status endpoint, and all existing session-mode behavior.
- Basic mode does not issue or depend on `knx_session`, `knx_csrf`, or `knx_login_csrf` cookies.
- No new dependencies.

## Review Focus

- Missing or malformed Basic credentials must return `401` with `WWW-Authenticate`, without leaking whether username or password was wrong; test in Task 1.
- A valid Basic credential must authorize protected pages and APIs even when cookies are absent; test in Task 1.
- Unsafe requests must reject absent, `null`, malformed, and unlisted Origin values before the route runs; test in Task 1.
- Existing cookie mode and login-origin fallback must remain unchanged by default; test in Task 1.
- Basic responses must not issue auth/session cookies and must not expose Authorization values in logs; test in Task 1.

---

### Task 1: Implement and document opt-in Basic authentication

**Files:**
- Modify: `web_ui/backend/storage.py` — add and validate `auth.mode` and `auth.allowed_origins` defaults/shape.
- Modify: `web_ui/backend/app.py` — add per-request Basic verification/challenge, origin validation for writes, and avoid session-cookie issuance in Basic mode.
- Modify: `web_ui/templates/index.html` — hide cookie-session logout control in Basic mode.
- Test: `tests/test_password_auth.py` — cover Basic challenge, credentials, protected page/API, Origin failures, no auth cookies, and unchanged default session flow.
- Modify: `installer/README.md` — document opt-in configuration, HTTPS, exact origins, relay Authorization-header requirement, and browser-cached credential/logout limitation.

**Interfaces:**
- Consumes: existing `cfg`, `_verify_login(username, password)`, `request`, and `login_csrf_allowed_origins` session-mode behavior.
- Produces: `auth.mode: "session" | "basic"` (default `"session"`) and `auth.allowed_origins: list[str]` (default `[]`); Basic-mode unsafe requests require an exact allowed `Origin`, falling back to `Referer` only if Origin is absent.

- [ ] **Step 1: Add failing tests for Basic-mode configuration and authentication**

  Cover: default mode remains session; invalid mode or origin-list shape raises `ValueError`; Basic requests without credentials and with incorrect credentials return `401` plus `WWW-Authenticate`; valid Basic credentials access `/` and a protected API without cookies; successful responses do not set `knx_session`, `knx_csrf`, or `knx_login_csrf`; captured application logs do not contain the Authorization value.

- [ ] **Step 2: Run the new focused tests and confirm they fail**

  Run: `python -m pytest tests/test_password_auth.py -q`
  Expected: failures because configuration and Basic-mode request handling are not implemented.

- [ ] **Step 3: Add failing tests for write-origin enforcement and session compatibility**

  Cover: an allowed exact Origin permits a valid authenticated write; absent Origin with allowed Referer permits it; absent/unlisted/`null`/malformed Origin rejects before the endpoint; invalid explicit Origin is not rescued by Referer; existing session-cookie login and CSRF tests still pass.

- [ ] **Step 4: Run focused tests and confirm only the new behavior fails**

  Run: `python -m pytest tests/test_password_auth.py -q`
  Expected: the new Basic-mode assertions fail; existing session-mode tests remain green.

- [ ] **Step 5: Implement config validation and Basic request handling**

  Add `auth.mode` defaulting to `session` and an empty `auth.allowed_origins` list. In Basic mode, verify `request.authorization` credentials with `_verify_login`; return a generic 401 with `WWW-Authenticate: Basic realm="KNX to OpenHAB", charset="UTF-8"` on failure. For unsafe methods, require a canonical exact Origin from `auth.allowed_origins`, using Referer only when Origin is absent. Do not create or check cookie sessions in this mode. Keep the current session branch unchanged.

- [ ] **Step 6: Run focused tests and verify both auth modes**

  Run: `python -m pytest tests/test_password_auth.py -q`
  Expected: all session-mode and Basic-mode tests pass.

- [ ] **Step 7: Hide session logout UI in Basic mode and document setup**

  Pass the effective auth mode to `index.html`; show the existing logout button only in session mode. Document a config example with `"mode": "basic"` and exact `"allowed_origins": ["https://mcrelay.greiner-wue.de"]`, HTTPS requirement, `Authorization` forwarding, rate-limit behavior, and inability to reliably log out while the browser retains Basic credentials.

- [ ] **Step 8: Run checks and inspect the final diff**

  Run: `python -m pytest tests/test_password_auth.py -q`, `python -m black --check web_ui/backend/app.py web_ui/backend/storage.py tests/test_password_auth.py`, `python -m isort --check-only web_ui/backend/app.py web_ui/backend/storage.py tests/test_password_auth.py`, `python -m flake8 web_ui/backend/app.py web_ui/backend/storage.py tests/test_password_auth.py`, `python -m mypy --platform linux web_ui/backend/app.py web_ui/backend/storage.py`, and `git diff --check`.
  Expected: all focused tests and checks pass. Full Linux CI must confirm before merge; live relay verification remains necessary because Basic mode requires the relay to pass Authorization.
