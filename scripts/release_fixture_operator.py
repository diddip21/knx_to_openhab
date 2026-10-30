"""Guarded own-inner release fixture operator. Separate review/permission required.

No command runs on import. The only transport targets the original named outer
WSL provider and inner machine. There are no repair, force, cleanup or host modes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance"
PHASES = (
    "prepare-fixture",
    "stable-update",
    "no-update",
    "checksum-rejection",
    "migration-rejection",
    "retry",
)
HOSTS = (
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
)
CODE_FILES = (
    "release_fixture_data.py",
    "release_fixture_server.py",
    "release_fixture_operator.py",
    "release_fixture_guest.py",
)
ORIGINAL_FILES = {
    "scripts/probe_harness_adoption.py": "e592462094abd5cbe1dc2fd4195cdb52b8f929f66edc5304cc7a744b8bd672d8",
    "scripts/nested_acceptance.py": "0ddf4c4d5a552c487bc1e46c88d31ffe4fa5337f06db3bb86f5001e1eb3b95a1",
}
ORIGINAL_RECEIPT_SHA256 = "77fae5534ff26c51a920136735d4e59dcc55c3a397c895aae3424508a933ec1c"
ORIGINAL_HARNESS_SHA256 = "645f294d50f33eab28bc6b19b9b213d5e01f0d325e3d94c25a74787253cecc73"
ORIGINAL_POSTPASS_SHA256 = "ed53b84f1bf13321af77837f307983ce1e8aff69c84f4bcdde5174859d872659"
ORIGINAL_PIP_EVIDENCE_SHA256 = "ab7fea10bd869d02fb07e2e0c73ecb0bae4f0c6fd929b1e7c9219f65b8a19d3f"


def authorize(phase, authorized_phase):
    if phase not in PHASES or authorized_phase != phase:
        raise ValueError("Exact separate controller phase authorization required")


def hosts_bytes(original):
    text = original.decode("utf-8")
    for line in text.splitlines():
        names = line.split("#", 1)[0].split()[1:]
        if any(name.lower().rstrip(".") in HOSTS for name in names):
            raise ValueError("Existing fixture host mapping; no adoption")
    if original and not original.endswith(b"\n"):
        raise ValueError("Noncanonical hosts terminator")
    return original + ("127.0.0.1 " + " ".join(HOSTS) + "\n").encode()


def check_sequence(phase, previous, current):
    expected = {
        "stable-update": (None, "0.1.0"),
        "no-update": ("stable-update", "0.1.1"),
        "checksum-rejection": ("no-update", "0.1.1"),
        "migration-rejection": ("checksum-rejection", "0.1.1"),
        "retry": ("migration-rejection", "0.1.1"),
    }
    if phase not in expected or (previous, current) != expected[phase]:
        raise ValueError("Unknown current version/phase history; no adoption or retry")


def terminal(phase, request, journal, status):
    if str(UUID(request)) != request:
        raise ValueError("Canonical real request UUID required")
    if (
        journal.get("request_id") != request
        or status.get("request_id") != request
        or journal.get("channel") != "stable"
    ):
        raise ValueError("Request/root claim/ack mismatch")
    if journal.get("phase") not in ("committed", "rolled-back"):
        return False
    expected = "committed" if phase in ("stable-update", "retry") else "rolled-back"
    if journal["phase"] != expected or status.get("phase") != expected:
        raise ValueError("Unexpected terminal transaction; stop, never retry")
    if phase == "no-update" and status.get("message") != "No newer compatible release":
        raise ValueError("Generic rollback is not a successful no-update outcome")
    return True


def login_token(text):
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tokens = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "input" and values.get("name") == "csrf_token":
                self.tokens.append(values.get("value"))

    parser = Inputs()
    parser.feed(text)
    if len(parser.tokens) != 1 or not parser.tokens[0]:
        raise ValueError("Missing/ambiguous login CSRF")
    return parser.tokens[0]


class AuthenticatedAPI:
    """Real cookie + login-CSRF flow, fixed loopback only; never prints secrets."""

    def __init__(self, credential):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.base = "http://127.0.0.1:8085"
        status, body = self.call("/login")
        if status != 200:
            raise ValueError("Login page refused")
        token = login_token(body.decode())
        cookie = self.cookie("knx_login_csrf")
        if cookie != token:
            raise ValueError("Login CSRF cookie mismatch")
        form = urllib.parse.urlencode(
            dict(username=credential["user"], password=credential["password"], csrf_token=token)
        ).encode()
        status, _ = self.call(
            "/login", data=form, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if status != 200 or not self.cookie("knx_session") or not self.cookie("knx_csrf"):
            raise ValueError("Protected administrator authentication failed")

    def cookie(self, name):
        values = [c.value for c in self.cookies if c.name == name and c.domain == "127.0.0.1"]
        return values[0] if len(values) == 1 else None

    def call(self, path, *, data=None, headers=None, method=None):
        if path not in ("/login", "/api/version/update", "/api/version/log"):
            raise ValueError("Fixed API route required")
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers or {}, method=method
        )
        try:
            response = self.opener.open(request, timeout=40)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Oversized API response")
            return response.status, raw

    def submit(self):
        # No JSON and no data body: exercise the application's default stable path.
        return self.call(
            "/api/version/update", method="POST", headers={"X-CSRF-Token": self.cookie("knx_csrf")}
        )


def code_digest():
    values = {
        name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
        for name in CODE_FILES
    }
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_original_wheels(manifest, original):
    actual = [{key: item[key] for key in ("name", "size", "sha256")} for item in manifest["wheels"]]
    if sorted(actual, key=lambda x: x["name"]) != sorted(original, key=lambda x: x["name"]):
        raise ValueError("Fixture wheel bytes differ from the original read-only receipt")


def pinned(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Original input/code pin mismatch")
    return raw


def guest_payload(phase, approval, source, nonce, baseline, fixture, files):
    authorize(phase, phase)
    guard = (ROOT / "scripts/probe_harness_adoption.py").read_bytes()
    operator = (ROOT / "scripts/release_fixture_operator.py").read_bytes()
    guest = (ROOT / "scripts/release_fixture_guest.py").read_bytes()
    return (
        "import sys,os,json,hashlib,stat,subprocess,time,types\nfrom pathlib import Path\n"
        "sys.dont_write_bytecode=True\n"
        + f"exec(compile({guard!r},'<original pinned guard>','exec'))\n"
        + f"approval={approval!r}\nsource_approval={source!r}\nnonce={nonce!r}\n"
        + "refuse_cached_modules(sys.modules)\nroot=verify_tree(approval)\n"
        + "sys.path[:0]=[str(root),str(root/'tests/integration')]\n"
        + "import test_update_systemd as harness\nverify_origins(approval,harness)\n"
        + "harness._check_virtualization('systemd-nspawn',nonce)\n"
        + "from scripts import nested_systemd_fixture as fixture,nested_fixture_repair as repair,nested_fixture_state as state\n"
        + "if os.name!='posix' or os.geteuid()!=0 or Path('/etc/machine-id').read_text().strip()!=repair.MACHINE_ID: raise ValueError('Wrong inner root')\n"
        + "production=repair.verify_probe_source(source_approval,SOURCE_HEAD)\n"
        + "admin=fixture.load_approved_admin(production)\nverify_admin_origins(source_approval,admin)\n"
        + "from installer.update_core import secure_fs as fs\n"
        + "from installer.update_core.transaction import load_paths\n"
        + "if load_paths(fixture.PATHS_FILE)!=fixture.expected_paths(): raise ValueError('Off-fixture paths')\n"
        + "fixture.validate_probe_roots(fixture.expected_paths())\nfixture.validate_preparation()\n"
        + "for relative in admin.BUNDLE:\n"
        + " if hashlib.sha256(fs.read_regular(Path('/usr/local/libexec/knx_to_openhab')/relative,1024*1024)).hexdigest()!=source_approval['files']['installer/'+relative]['sha256']: raise ValueError('Installed bundle changed')\n"
        + "admin.check_worker()\nadmin.check_worker_sudo()\n"
        + "module=types.ModuleType('fixture_operator')\nmodule.__file__='/root/knxoh-release-fixture/release_fixture_operator.py'\nsys.modules[module.__name__]=module\n"
        + f"exec(compile({operator!r},'<reviewed fixture controller>','exec'),module.__dict__)\n"
        + f"exec(compile({guest!r},'<reviewed fixture guest operator>','exec'))\n"
        + f"run({phase!r},{baseline!r},{fixture!r},{files!r})\n"
    )


def dispatch(command, payload, evidence_dir, phase):
    """One transport attempt; timeout/launch failure is unknown, never retryable here."""
    try:
        result = subprocess.run(
            command, input=payload, text=True, capture_output=True, timeout=1800
        )
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout, error.stderr
        exit_text, code = "unknown: timed-out; do not resubmit", 124
        outcome = dict(phase=phase, outcome="timed-out-unknown", transport_exit=None)
    except OSError as error:
        stdout, stderr = (
            b"",
            f"Transport launch failed: {type(error).__name__}; errno={error.errno}",
        )
        exit_text, code = "unknown: launch-failed; do not resubmit", 125
        outcome = dict(phase=phase, outcome="launch-failed-unknown", transport_exit=None)
    else:
        stdout, stderr = result.stdout, result.stderr
        exit_text, code = str(result.returncode), result.returncode
        outcome = dict(phase=phase, outcome="transport-completed", transport_exit=code)
    for name, value in (("observations.jsonl", stdout), ("stderr.log", stderr)):
        raw = value.encode("utf-8") if isinstance(value, str) else value or b""
        (evidence_dir / name).write_bytes(raw)
    (evidence_dir / "exit.txt").write_text(exit_text, encoding="utf-8")
    (evidence_dir / "dispatch-outcome.json").write_text(
        json.dumps(outcome, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("Own-inner fixture transport:", outcome["outcome"], "controller exit:", code)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--authorize-phase", required=True, choices=PHASES)
    parser.add_argument("--code-sha256", required=True)
    parser.add_argument("--fixture-root", required=True, type=Path)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    authorize(args.phase, args.authorize_phase)
    if code_digest() != args.code_sha256:
        raise ValueError("Independent reviewed fixture code pin required")
    for name, digest in ORIGINAL_FILES.items():
        pinned(ROOT / name, digest)
    sys.path.insert(0, str(ROOT))
    from scripts import nested_acceptance as provider
    from scripts import probe_harness_adoption as adoption
    from scripts.release_fixture_data import load_fixture, read_regular

    receipt = provider.decode_receipt(
        pinned(PRIVATE / "provider-receipt.json", ORIGINAL_RECEIPT_SHA256).decode()
    )
    approval = json.loads(
        pinned(PRIVATE / "probe-harness-approval-PENDING.json", ORIGINAL_HARNESS_SHA256)
    )
    source = json.loads(
        pinned(PRIVATE / "repair-pins-c0e381c/source-approval.json", adoption.SOURCE_PIN)
    )
    adoption.validate_approval(approval)
    adoption.validate_source(source, adoption.SOURCE_HEAD)
    baseline = {
        e["event"]: e
        for e in map(
            json.loads,
            pinned(
                PRIVATE / "probe-097-reviewed-01/postpass-observations.jsonl",
                ORIGINAL_POSTPASS_SHA256,
            )
            .decode()
            .splitlines(),
        )
    }
    manifest = load_fixture(args.fixture_root, args.fixture_sha256)
    if len(manifest["wheels"]) != 29:
        raise ValueError("All 29 original admitted wheels required")
    pip_evidence = pinned(
        PRIVATE / "release-pip-readonly-04/observations.jsonl", ORIGINAL_PIP_EVIDENCE_SHA256
    )
    original_wheels = [
        json.loads(line)["files"]
        for line in pip_evidence.decode().splitlines()
        if line.startswith("{") and json.loads(line).get("event") == "WHEELHOUSE"
    ]
    if len(original_wheels) != 1:
        raise ValueError("Original full wheel receipt missing/ambiguous")
    check_original_wheels(manifest, original_wheels[0])
    files = {
        name: base64.b64encode(read_regular(args.fixture_root / name)).decode()
        for name in manifest["files"]
    }
    files["fixture.json"] = base64.b64encode(
        read_regular(args.fixture_root / "fixture.json")
    ).decode()
    # Validate outer registration/preflight freshly for EVERY phase, before transport.
    provider.validate_receipt(receipt)
    provider.validate_registration(provider.registration())
    observations = provider.preflight(receipt)
    args.evidence_dir.mkdir(mode=0o700, exist_ok=False)
    (args.evidence_dir / "preflight.json").write_text(json.dumps(observations, sort_keys=True))
    payload = guest_payload(
        args.phase, approval, source, receipt["nonce"], baseline, manifest, files
    )
    (args.evidence_dir / "dispatch-sha256.txt").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )
    # Do NOT persist the payload: it includes the original private receipt nonce.
    command = [
        "wsl.exe",
        "-d",
        provider.DISTRIBUTION,
        "--",
        "/usr/bin/systemd-run",
        "--machine=" + provider.MACHINE,
        "--wait",
        "--pipe",
        "--collect",
        "/opt/knxoh-test-venv/bin/python",
        "-I",
        "-B",
        "-",
    ]
    return dispatch(command, payload, args.evidence_dir, args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
