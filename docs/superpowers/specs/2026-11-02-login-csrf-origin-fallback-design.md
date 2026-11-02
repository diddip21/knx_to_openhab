# Login CSRF Origin Fallback — Design

## Intent

Allow the login form to work through a relay that drops the `knx_login_csrf`
`Set-Cookie` header, without disabling authentication or weakening CSRF checks.
The normal cookie-based flow remains the default. The fallback applies only to
`POST /login` and is enabled only for explicitly configured public origins.

## Current behavior

`_render_login()` creates a time-limited signed form token and sends the same
value in the `knx_login_csrf` cookie. `_valid_login_csrf()` requires both values
to match and verifies the signature and 10-minute age. The relay is not
delivering the cookie to the browser, so login is rejected before credentials
are checked.

After successful authentication, the browser also needs the `knx_session`
(`HttpOnly`) and `knx_csrf` cookies. This change cannot compensate if the relay
also drops those cookies.

## Approaches considered

1. **Repair the relay/proxy (recommended where administratively possible).**
   Preserve `Set-Cookie` and `Cookie` headers and avoid caching login responses.
   This fixes the actual transport fault without changing the app's security
   model, but the Pi operator may not control the relay.
2. **Explicit-origin login fallback (selected for this change).** Keep the
   existing cookie-and-form-token check. If the login CSRF cookie is absent,
   accept only a valid, unexpired signed form token accompanied by an exact
   match against a configured public `Origin`; use an exact `Referer` origin
   match only when `Origin` is absent. This supports the relay while retaining
   a browser-origin CSRF defense. It does not solve missing session cookies.
3. **Remove CSRF validation or move session tokens into JavaScript storage.**
   Rejected: these weaken protection or require a broader, riskier
   authentication redesign.

## Proposed behavior

- Add `login_csrf_allowed_origins`, an explicit list of canonical origins such
  as `https://mcrelay.greiner-wue.de`. Default it to an empty list so existing
  installations retain current behavior unless configured.
- Always require a valid signed form token no older than 600 seconds.
- If the CSRF cookie is present, require an exact cookie/form-token match; a
  mismatch remains an error.
- If the cookie is absent, require an exact configured-origin match. Do not
  derive trusted origins from arbitrary `Host` or forwarded headers. Reject
  missing, `null`, malformed, or unlisted origins; when `Origin` is absent,
  permit the same check against the parsed `Referer` origin.
- Mark login responses `Cache-Control: no-store` to prevent shared caching of
  pages containing signed form tokens. Keep setting the existing CSRF cookie.
- Do not change authenticated-session CSRF validation, password verification,
  rate limits, or session-cookie flags.

## Acceptance criteria

- The existing cookie-backed login continues to pass its tests.
- A missing login CSRF cookie is accepted only with a valid signed token and a
  configured exact origin (or exact Referer fallback).
- Missing/unlisted origins, malformed/expired tokens, and mismatched present
  cookies are rejected before credential verification.
- The fallback is disabled by default and cannot be enabled by a request header.
- Login responses are not cacheable.
- Manual deployment validation confirms the relay forwards the post-login
  `knx_session` and `knx_csrf` cookies; if it does not, the relay still needs
  correction and this change alone will not complete sign-in.

## Scope and compatibility

This is a narrowly scoped login compatibility option. Existing deployments and
direct-access behavior remain unchanged until an administrator explicitly adds
the public origin to configuration. No authentication bypass is introduced.
