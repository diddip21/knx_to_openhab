# Local release-runtime fixture: default PyPI index with system TLS trust

Status: **design for controller review; not operational authorization**.
The default-index dependency path is admitted for implementation design by
read-only inspection. No fixture TLS handshake, dependency install, update,
rollback or reboot acceptance is claimed. Production remains the original
reviewed `2dcf3078b61283a41fd1ef38e34327e4f759d5c1` source and installed bundle.

## Intent and scope

Exercise the real installed updater through authenticated API/sudo/systemd, using
source-only release artifacts and the full unchanged requirements, without giving
the isolated guest outbound access or modifying production to accommodate a test.
This document narrows the dependency design in the
[earlier fixture outline](../2026-10-30-release-runtime-admission-blocker.md).
It does not introduce another checkpoint/enrollment framework.

No host/outer-WSL trust changes, production/helper/requirements changes, pip
configuration writes, added `PIP_*` variables, `--trusted-host`, disabled TLS,
preinstalled candidate venv, empty requirements or dependency-manager mocks.
Boot/offline-lock/corrupt-journal acceptance remains separate and open.

## Actual environment finding

Read-only queries, guarded by the original provider receipt, deployed harness,
guest identity, production source approval and installed bundle hashes, observed:

| Component | Actual inner-guest value |
| --- | --- |
| Distribution | Ubuntu 24.04 LTS (Noble), Debian-derived; not a Debian acceptance run |
| `/usr/bin/python3` | CPython 3.12.3, package `3.12.3-0ubuntu2.1` |
| Python / venv packages | `python3.12` / `python3.12-venv` `3.12.3-1ubuntu0.17` |
| Ensurepip selected seed | `/usr/share/python-wheels/pip-24.0-py3-none-any.whl` |
| Seed package | `python3-pip-whl 24.0+dfsg-1ubuntu1.3` |
| Seed wheel SHA-256 | `e995a37590643450898cfa5bd5113831a547506cd545c335a409339d0c1e87ab` |
| CA package | `ca-certificates 20260816ubuntu0.24.04.1` |
| Pip default index | `https://pypi.org/simple` |
| Pip truststore feature default | Off (`features_enabled=[]`) |
| Vendored certifi / Requests default CA | `/etc/ssl/certs/ca-certificates.crt` |
| Constructed pip session | `verify=True`; default HTTPS adapter, no request made |

The seed was imported directly from ensurepip's selected wheel in an isolated,
bytecode-disabled diagnostic process. No seed/venv/package was installed or
modified. Its `certifi.core` explicitly ends with Debian overrides of `where()`
and `contents()` using the system bundle. Its actual Requests `cert_verify()`
uses that bundle and `CERT_REQUIRED` for verified HTTPS. Thus upstream pip's
pre-24.2 truststore default does **not** prevent this packaged seed from trusting
a correctly installed inner-only system CA. No pip upgrade or additional argv is
needed on the observed target.

This is not evidence that arbitrary upstream pip24.0, another Debian release or
all supported deployments have the same patch. Before operational authorization,
recheck the same package/wheel/CA paths and hashes. An unexpected seed refuses the
fixture; it is not automatically upgraded or patched. Record any separately
chosen target/runtime as acceptance-environment configuration, not a production fix.

The existing wheelhouse has 29 wheels. All ZIP CRCs pass. A local static metadata
walk of the original requirements and Linux/CPython3.12 markers finds 28 required
projects present with compatible version and Requires-Python constraints; the
extra wheel is `pytest-timeout`. This is not a pip resolver, platform-tag test or
successful installation. Do not promote that audit to dependency acceptance.

## Approaches and selection

1. **Selected by the controller:** preserve default PyPI URLs, map only approved
   names to inner loopback, and use the system trust bundle with an inner-only CA.
   Read-only inspection establishes that the existing packaged seed supports it.
2. `/etc/pip.conf` no-index/find-links: rejected. The original helper sets
   `PIP_CONFIG_FILE=/dev/null`; retain the existing diagnostic as evidence about
   that channel only. Do not change production to revive it.
3. New pip seed/package: unnecessary for this observed target. It would change the
   environment and require a separately reviewed package/version decision; no such
   change is authorized or proposed. An unpatched upstream24.0 target would need
   that separate decision rather than hidden flags or a modified certifi wheel.

## Portable implementation slice after design approval

Use standard-library fixture code and existing test tooling; no new dependency.
Keep artifact/index generation distinct from the privileged operator. Portable
builders must have no WSL/service/hosts/trust-install side effects.

### Release artifacts

Export the exact original production Git commit into exclusive local staging.
Verify the original source map before editing; initialize a temporary Git index
there and run that exported source's real `scripts/build_release.py`.
Build normal `0.1.1` and `0.1.2` with only `VERSION` changed. Requirements,
protocol1/schema1 contract and production helper bytes remain intact. Record the
complete delta map, archive members, bytes, deterministic hashes and sidecars.
Do not tag/publish or package a wheelhouse, venv, private proof or test harness.

The checksum-negative response serves the unchanged normal archive with a wrong
sidecar. A separately named migration-negative0.1.2 fixture changes only the
copied migration CLI to a recorded nonzero exit; never replace the installed
privileged helper. Preserve normal-success fixtures independently.

### PEP503 index and complete file bytes

Inventory the existing `/opt/knxoh-wheelhouse` with bounded no-follow,
single-link regular-file/owner/ancestry checks. Read the full wheel bytes and
record size/SHA-256. Determine each project's name/version from its top-level
`.dist-info/METADATA`, not nested vendored metadata (setuptools contains both).
Cross-check filename/metadata version/project and target-compatible wheel tags.
Reject duplicate/ambiguous members, malformed wheels, names or metadata.

Normalize project names with `re.sub(r"[-_.]+", "-", name).lower()`; e.g.
`Flask` becomes `flask`, `argon2_cffi` becomes `argon2-cffi`, and
`pytest_dependency` becomes `pytest-dependency`. Serve all29 admitted wheels,
including the28-project static dependency closure, not just direct requirements.

Serve HTML at `https://pypi.org/simple/` and `/simple/<normalized-name>/`.
Each project page links to an explicitly inventoried URL of the form
`https://files.pythonhosted.org/packages/<sha256>/<filename>#sha256=<sha256>`.
The anchor text is the escaped original wheel filename. Use correct content type,
Requires-Python attributes when present and complete Content-Length/file bytes.
Do not advertise unimplemented PEP658 metadata links, JSON APIs or sdists.
Support pip's HTML fallback even when its Accept header also offers JSON.
Fragments are client-side hash checks, not part of the server route.

The file route is an exact allowlist into immutable inventoried bytes, not a
filesystem join or directory server. Unknown/case-mismatched names, traversal,
queries, methods and Host/path combinations fail closed. No outbound proxy,
redirect, upload or package download facility. HEAD, if supported, returns the
same headers and no body; GET returns every original wheel byte. No silent
truncation, placeholder archive or post-build wheel patching.

## Inner HTTPS setup: later explicit permission gate

Implement/review, but do not execute yet, one fixed own fixture unit on loopback443.
Generate a private test CA and server certificate with exact approved SAN names:
`api.github.com`, `github.com`, `release-assets.githubusercontent.com`,
`pypi.org`, `files.pythonhosted.org`. Keys and trusted server/control files are
root-owned outside candidate/worker-writable trees. Unknown existing fixture
state refuses preparation. Preserve original hosts/CA/unit bytes and identity.
Add only those loopback host mappings, preserving unrelated entries and refusing
conflicts. Install/trust the CA only in the original owned inner guest; never in
Windows or outer WSL. No `/etc/pip.conf`, candidate pip config, certificate-env
override or `PIP_*` fixture override. The production helper's existing literal
environment and argv remain unchanged.

Serve the original GitHub latest/asset URLs with exact release names/flags and
checksums. Use fixed root-controlled phase selections and immutable bytes; worker
requests cannot select phases. Keep certificate/CA verification enabled for both
the stdlib GitHub downloader and the actual pip HTTPS client. After explicit
setup authorization, require verified handshakes for both host families and
negative wrong-host/untrusted-chain controls before update permission. A portable
test using a temporary CA file is not proof of guest system trust.

The actual metadata/download/dependencies stages should have `PrivateNetwork=no`
and access only the owned guest loopback fixture; verify their real namespaces.
Extract/migrate retain `PrivateNetwork=yes`. Require no non-loopback guest
network/outbound route. Do not weaken production namespace or systemd settings.

## Tests and operational gates

1. **Now:** controller reviews this design and retained read-only receipts. No
   remaining pip-version choice is required for the observed Ubuntu seed.
2. **Portable TDD:** add failing tests for canonical names (including underscores,
   dots and mixed case), top-level versus nested metadata, ambiguous/invalid
   inputs, duplicate files, symlinks, unknown state and deterministic output.
   Test HTML links/hash fragments and full real wheel bytes end-to-end over a
   temporary TLS listener without global trust installation. Test hostname/chain
   rejection, exact allowed routes and no arbitrary file access. Test reproducible
   source builds/delta maps and unchanged full requirements/helper. Then implement
   the narrow builders/server and run focused tests before broader checks.
3. **Operator review:** review exact commands, existing provider/source/hash reuse,
   guarded CA/hosts/unit effects, private auth handling and phase-specific cleanup.
   No generic framework or observed-state checkpoint per phase. Independently
   review code/tests before authorizing any guest setup. Commands must exist and
   have been inspected before they are presented as executable acceptance gates.
4. **Setup permission:** separately authorize only inner fixture preparation and
   actual default-client TLS verification. Record the runtime/seed/package hashes.
   No updater or app-unit effect is implicit in this gate.
5. **Stable permission:** authenticate using original protected login receipt,
   real login-CSRF/cookie flow and real `POST /api/version/update` (no body for
   stable). Observe matching request/root claim, fixed sudo unit start, journal,
   all real stages, quiescence, snapshot/current switch, notify and health0.1.1
   from its own final-path full venv. A real failure stops; no repair/retry.
6. **Later phase permissions:** no-update with no archive/UI-restart/candidate
   mutation, checksum rejection, migration rejection/healthy rollback, then a
   fresh-UUID retry through the real coordinator. Observe concurrent POST409 only
   during a confirmed active transaction; do not reset state to force a race.
   Lost HTTP responses mean unknown/in-progress, never automatic resubmission.

Across all operational phases verify the original installed production bundle,
3354-entry initial0.1.0 tree, protected configuration, credentials and external
sentinels against original receipts. Keep the two exact retained historical/probe
UUID artifact trees separately worker-owned and unchanged; never pass them to
the immutable-root collector or add broad-prefix exemptions. Changes must be
explained by exact own fixture/transaction identities, not newly approved snapshots.

On failure preserve journal/candidates/raw evidence privately. No reset-failed,
owner repair, bootstrap/readiness rerun, forced current, manual candidate deletion,
reboot or host package/trust effects. Cleanup is limited to separately approved
own-fixture actions with exact before/installed-byte checks.

## Remaining uncertainty

Actual system-trusted fixture TLS, resolver/platform-tag acceptance, full venv
size/tree limits and installed end-to-end update/rollback are still unproved.
Only real guarded execution can establish them after design/code/test review and
explicit operational permission. The old pip-config diagnostic is not that proof
and is not a reason to block implementation of this default-index design.
