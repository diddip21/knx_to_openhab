#!/usr/bin/env python3
"""Register the first admin through openHAB's supported local OAuth signup page.

Called only by the disposable VM systemd smoke test. This uses openHAB's own
/auth form and its server-issued CSRF token; it does not modify user storage,
disable authentication, or require Karaf console access.
"""

from __future__ import annotations

import base64
import hashlib
import html.parser
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

ORIGIN = "http://127.0.0.1:8080"
REDIRECT_URI = ORIGIN + "/"
LINKS_URL = ORIGIN + "/rest/links"


class HiddenFormInputs(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        name = values.get("name")
        if name and values.get("type", "").lower() == "hidden":
            self.inputs[name] = values.get("value") or ""


class StopRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def assert_basic_auth(username: str, password: str) -> bool:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    request = Request(
        LINKS_URL,
        headers={"Accept": "application/json", "Authorization": f"Basic {token}"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status == 200
    except (HTTPError, URLError, TimeoutError):
        return False


def create_account(username: str, password: str) -> bool:
    # OAuth parameters are local-only and are required by the signup servlet.
    verifier = "knxoh-ci-smoke-verifier-46cc6e76cd957d05"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode("ascii")
        .rstrip("=")
    )
    params = {
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "client_id": REDIRECT_URI,
        "scope": "read",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    opener = build_opener(StopRedirect)
    request = Request(ORIGIN + "/auth?" + urlencode(params), headers={"Accept": "text/html"})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"Signup form returned HTTP {response.status}")
        page = response.read().decode("utf-8")
    parser = HiddenFormInputs()
    parser.feed(page)
    csrf_token = parser.inputs.get("csrf_token")
    if not csrf_token:
        raise RuntimeError("The signup page did not provide a CSRF token")
    params["csrf_token"] = csrf_token
    params["username"] = username
    params["password"] = password
    params["password_repeat"] = password
    post = Request(
        ORIGIN + "/auth",
        data=urlencode(params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with opener.open(post, timeout=20) as response:
            # Some servlet configurations use a 200 confirmation page.
            return response.status in (200, 302, 303)
    except HTTPError as error:
        if error.code in (302, 303):
            return True
        raise RuntimeError(f"Signup POST returned HTTP {error.code}") from error


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: create_openhab_admin.py USERNAME PASSWORD")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This helper is restricted to disposable GitHub CI.")
    username, password = sys.argv[1:3]
    if not username or len(password) < 12:
        raise SystemExit("Invalid synthetic CI test account credentials")
    last_error = ""
    for attempt in range(1, 9):
        if assert_basic_auth(username, password):
            print("PASS: test-only openHAB administrator can access REST /links")
            return
        try:
            create_account(username, password)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
            last_error = f"{type(error).__name__}: {error}"
        # The user registry can initialize after the HTTP server has bound.
        for _ in range(3):
            if assert_basic_auth(username, password):
                print("PASS: first administrator created using openHAB /auth signup")
                return
            time.sleep(2)
        print(f"Admin registration not yet ready (attempt {attempt}): {last_error}", flush=True)
    raise SystemExit("Could not create or authenticate disposable openHAB administrator")


if __name__ == "__main__":
    main()
