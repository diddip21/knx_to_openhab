# Release-runtime acceptance: pip configuration finding and default-index alternative

**Review-stage only. No guest setup, update, rollback or boot was executed.**
Production remains the reviewed `2dcf3078b61283a41fd1ef38e34327e4f759d5c1` bundle;
this change does not replace that bundle or alter application code.

**Correction after read-only investigation:** the failure below concerns only the
proposed `/etc/pip.conf` channel. It does not block all offline dependency fixtures
and does not require a production change. The existing Ubuntu ensurepip seed has a
Debian-patched vendored certifi using the system CA bundle, so an inner-only,
TLS-verified fixture at pip's default PyPI URLs is viable for implementation review.
See [the narrowed design](specs/2026-10-30-local-release-runtime-fixture-design.md).
No fixture CA trust, hosts mapping, package update or HTTPS request was performed
by that investigation; actual dependency installation remains unverified.

## Finding and bounded reproduction

The initial proposed acceptance strategy depended on the real child installing the full
unchanged `requirements.txt` from an inner-only offline wheelhouse configured in
`/etc/pip.conf`. The exact reviewed `installer/update_prepare.py` instead sets
`PIP_CONFIG_FILE=/dev/null`, including when invoking `pip --isolated install`.
Pip treats this value as **disable all configuration files**, not merely disable
per-user configuration. Thus a global `no-index`/`find-links` fixture cannot work
through the proposed configuration channel.

Run the local-only diagnostic from the checkout root:

```powershell
python -B -m scripts.check_release_runtime_admission
```

Expected admission result is **exit 2**, `admitted: false`. It reads the exact
reviewed Git blob (not the current harness helper), creates a fresh native
`venv --copies`, writes only that temporary venv's pip configuration, and invokes
real `python -I -m pip --isolated config get global.no-index` twice. Without the
null setting the positive control returns `true`/exit0; with the setting pip
returns `No such key`/exit1. No pip package installation or network request occurs.
The diagnostic's temporary directory alone is cleaned up; it has no guest cleanup
authority. Windows uses native `pip.ini`/`nul` to exercise the same pip semantics;
this is **not** an actual Linux update failure or proof of the guest's pip version.

The original helper SHA-256 is
`260b76e82ca6ab712a84362a0f022d783db62f6e2b114fe442da8a2229a3106f`.
The tests pin that original blob and its full venv/pip argv. Green diagnostic tests
mean this configuration-channel incompatibility is detected; they do not mean
offline installation succeeds or that the default-index alternative is blocked.

Do not work around this by changing requirements, precreating the candidate venv,
changing helper environment/argv, exporting `PIP_*`, making global host dependency
changes, giving the guest outbound access, or replacing the production helper
from this harness. Any production policy correction needs its own review and
explicit installed-component authorization. No such correction is proposed here.

## Corrected admission inputs

The earlier statement that the private execution reports were unavailable was
incorrect. Both exist under
`.superpowers/sdd/2026-10-28-transactional-release-updater/wsl-acceptance/` and have
now been read in full, together with the original pinned provider/source inputs.
They record actual readiness/version `0.1.0` and the later actual new-UUID hostile
probe PASS; historical failed attempts remain historical failures. Reuse those
original guards and receipts. Do not reconstruct/enroll a baseline or rerun readiness.

Before a runtime-capable runner can be submitted for review:

1. Retain the real failed configuration-channel diagnostic, but use the default
   `https://pypi.org/simple` index and `https://files.pythonhosted.org/` wheel links
   with system CA validation. No pip configuration/environment/argv or production
   change is needed for the observed Ubuntu-packaged seed.
2. Reuse the existing original provider receipt, production approval, private
   preservation evidence and exact known probe artifact names. These inputs are
   present; they are not missing prerequisites. Keep them private.
3. Confirm the guest wheelhouse contains every unchanged production dependency
   and transitive wheel for the guest Python/platform, readable by UID997 with
   protected ancestry. No sdist build/network fallback, host package install or
   empty-requirements substitute is admissible.

## Bounded implementation design (not implemented or approved to execute)

Keep one small operator with an explicit phase allowlist:
`prepare-fixture`, `stable-update`, `no-update`, `checksum-rejection`,
`migration-rejection`, `retry`. Do not add generic adopt, wipe, repair, resume,
boot, journal-corruption or force-activation actions. Preparation is exclusive;
unknown existing fixture files or release directories refuse admission. Execute
only inside `KNXOH-Acceptance-20261030` → `knxoh-acceptance`, never default/custom
host Ubuntu. Recheck the existing original-provider/inner-identity guards before
each phase, plus no non-loopback interface or outbound route.

### Release fixtures

- Export the **exact** reviewed production commit using native Git archive into
  a never-existing trusted staging directory. Validate against the existing source
  approval, initialize a native temporary Git index there, and run that source's
  actual `scripts/build_release.py`. Never tag, publish, mutate a user checkout or
  substitute the current test harness as production source.
- Build `0.1.1` and `0.1.2` with only tracked `VERSION` changes. Keep full original
  requirements and protocol-1/schema-1 contract. Record an explicit before/after
  hash map of every fixture delta and archive/checksum. Each source tar must be
  under32MiB and source-only; no private receipts, credentials, wheelhouse or venv.
- A separate `0.1.2` migration-failure variant may alter only the copied-migration
  CLI to exit nonzero. Record its exact bytes/hash transparently; never install it
  as a privileged helper. Checksum rejection instead serves an intentionally wrong
  sidecar against the unchanged normal tar. Run normal success first. A deliberate
  readiness-failure body is a later separately reviewed fixture, not a timeout
  relaxation. Optional prerelease testing is not required for this bounded stage.

### Inner-only HTTPS fixture

- Serve the production URLs verbatim: `https://api.github.com/repos/diddip21/`
  `knx_to_openhab/releases/latest`, and the two exact GitHub download URLs under
  `/diddip21/knx_to_openhab/releases/download/v<VERSION>/`. Metadata uses real
  draft/prerelease flags, exact asset names and HTTPS URLs. Reject unknown Host,
  path, method, query and control-file state; no generic directory serving.
- Generate the CA/key only inside the owned inner fixture. Root-only keys and
  trusted helper source must stay outside candidate-writable trees. Trust the CA
  **only in that inner disposable guest**. Never in Windows, outer WSL or production.
  Preserve unrelated `/etc/hosts` lines; add loopback mappings only for owned
  `api.github.com`, `github.com`, `release-assets.githubusercontent.com` names.
  Include `pypi.org` and `files.pythonhosted.org` for the default-index fixture.
  Refuse existing conflicting mappings and unknown CA/hosts/unit fixture state.
  Do not write pip configuration or add pip environment overrides.
- Bind443 on loopback with a fixed root-owned trusted server/helper and an own
  fixture unit. Do not execute candidate code as root. Do not disable HTTPS
  verification, checksum checks, URL checks or startup guards. Production ignores
  proposed remote-API environment overrides: none are a valid test mechanism.
- Observe actual metadata/download child `PrivateNetwork=no` and its container
  network namespace/loopback access to the TLS server; migration remains
  `PrivateNetwork=yes` and cannot reach that server. A portable routing or TLS
  certificate test is not runtime namespace evidence.

### Real API pipeline and preservation

Read `/root/knxoh-acceptance-login.json` using the existing protected bounded reader;
never print the password, cookies, CSRF values or nonce. GET `/login` with a cookie
jar; POST the real username/password and matching signed `knx_login_csrf` form
token. Retain `knx_session` plus `knx_csrf`; send the latter as `X-CSRF-Token` on
POST `/api/version/update` with **no body** for default stable. Require real matching
request-ID acknowledgement and root claim, then inspect the protected journal;
HTTP acceptance alone is not completion. Do not fabricate requests/claims/status
or invoke the coordinator directly. The UI must issue its real exact sudo fixed
unit start, and the actual updater must survive outside the UI cgroup.

Observe actual stages, locks, maintenance, quiescence, snapshot, atomic current
switch, installed startup guards, notify readiness and direct authenticated API
health/version. Require `0.1.1` served by its **own final-path full candidate venv**
and the matching root journal/status committed. Treat disconnects during UI
restart as unknown/in-progress; reconnect with the same session and examine the
matching request, never resubmit on a lost HTTP response.

During a confirmed active request, a concurrent authenticated POST must return409
without overwriting its request/claim. Avoid resetting state to provoke this race.
For `no-update`, require no archive download, UI restart, candidate or config
mutation; the ordinary request/status/replay-ledger activity is allowed. Checksum
and migration rejection must leave `0.1.1` serving and restore/refinalize healthy
old state with matching terminal journal. A retry requires a fresh UUID and the
real coordinator's own cleanup/recovery policy; do not delete candidates manually.

Each phase verifies the unchanged installed production bundle, original frozen
3354-entry `0.1.0` tree, original config/generator/secrets/runtime/output/backups
sentinels, and its explicit expected current version. Do not apply the3354 count
to the new full venv. Keep worker-owned known probe artifacts separate from frozen
root application trees; never use their manifests as recovery authority. Derive
allowances from explicit known transaction IDs/fixtures, not path-prefix exclusions
or a newly collected approved checkpoint for every phase.

### Failure/cleanup boundary

On a real production defect, stop with RED evidence. Do not alter production,
increase deadlines, rerun bootstrap/repair/readiness, reset-failed, remove arbitrary
data, force current, or corrupt a journal. Preserve candidates, protected journal,
requests and logs for controller review. An explicitly guarded stop of only the
own HTTPS fixture unit may be needed; it must not stop app units or erase CA,
hosts/config evidence. Restoration/removal of known fixture files requires a
separate reviewed cleanup step comparing their exact original/installed bytes.

## Runtime permission still needed

There is deliberately **no full-update runtime command in this commit**. The
default-index path is viable for design review, but its runner is not implemented.
After reviewing that design and existing private inputs, review fixture artifacts,
TLS setup and phase implementation before authorizing any inner
CA/hosts/unit writes. Separately authorize the first actual authenticated
stable update, then each negative/retry phase. Boot/offline-lock/corrupt-journal
acceptance remains outside this scope and **NOT VERIFIED**.
