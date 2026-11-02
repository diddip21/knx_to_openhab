# Cookie-less HTTP Basic Authentication — Design

## Intent

Allow the Web UI to remain usable when the MeshCentral relay drops `Cookie` and
`Set-Cookie` headers, and the administrator cannot change the relay. The current
session-cookie flow remains the default for normal installations.

## Approaches

1. **Repair the relay.** Preserve the existing session-cookie design. This is
   the simplest and strongest option, but the user cannot configure the relay.
2. **Optional HTTP Basic authentication (chosen).** The browser sends the
   existing username/password in an `Authorization` header over HTTPS on each
   request; the server verifies it without creating a cookie session. This
   avoids cookies, but requires the relay to pass `Authorization`. Browsers may
   retain Basic credentials until closed, so logout cannot reliably clear them.
3. **Browser-held bearer token.** Add token issuance and send the token on each
   request. This avoids cookies too, but requires more application changes and
   exposes a reusable token to page JavaScript. URL tokens are rejected because
   they can leak through history, logs, and referrers.

## Behavior

- Add an explicitly opt-in authentication mode; keep existing cookie sessions
  as the default and preserve existing configuration keys.
- In Basic mode, authenticate protected page/API requests using the configured
  username and password hash; do not issue or require `knx_session` or
  `knx_csrf` cookies.
- Continue requiring HTTPS in deployment. Never accept credentials in query
  strings or log the `Authorization` header.
- Since browser Basic credentials are sent automatically, require an exact
  allowlisted `Origin` for every state-changing request; use `Referer` only
  when `Origin` is absent, and fail closed otherwise. Preserve authentication
  and rate limiting.
- Keep the current `/login` cookie/session behavior unchanged when Basic mode
  is not selected. Explain Basic Auth's browser-cached credentials and logout
  limitations in the installer guide.

## Constraints and validation

- The relay must pass `Authorization`; if it strips that header too, neither
  Basic Auth nor a bearer header can work through it without relay changes.
- The current integration flow proves the login POST is accepted but the
  session does not persist. End-to-end validation must confirm the relay passes
  `Authorization` and all protected UI/API requests succeed without cookies.
- Add regression coverage for default session-mode compatibility, valid/invalid
  Basic credentials, origin rejection on writes, missing authorization, and
  absence of session cookies in Basic mode.

## Non-goals

- Do not disable authentication or CSRF defenses.
- Do not change the default authentication mode or remove session-cookie auth.
- Do not implement tokens in URLs or weaken the allowlist to wildcard matching.
