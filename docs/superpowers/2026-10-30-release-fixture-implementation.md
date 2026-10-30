# Local release fixture: implementation for independent review

Status: **implemented and locally tested; not operationally authorized**.
Implements the bounded
[approved fixture design](specs/2026-10-30-local-release-runtime-fixture-design.md).
Production remains the original `2dcf3078b61283a41fd1ef38e34327e4f759d5c1`.
No installed helper, requirements, configuration, application unit or updater was
changed or exercised by this implementation delivery. No subagents were used.

## Code responsibilities

| Source | Responsibility |
| --- | --- |
| `scripts/release_fixture_data.py` | Portable exclusive staging, verified original Git blobs, temporary native Git index, real exported release builder, full source/delta/archive maps and SHA sidecars; strict complete-wheel inventory and PEP503 HTML/file routes; whole fixture inventory/pin. No WSL, service or trust operations. |
| `scripts/release_fixture_server.py` | Stdlib TLS server with exact immutable Host/path allowlists, raw-target/method/body rejection, HTML fallback, full Content-Length/bytes, no filesystem URL mapping or proxy. Its standalone entry has a fixed private root and loopback443, and imports no candidate. |
| `scripts/release_fixture_operator.py` | Exact six-phase CLI, explicit separate phase/code/fixture authorization, original input pins and fresh provider preflight for each dispatch; real cookie/login-CSRF client and empty-body default-stable POST. |
| `scripts/release_fixture_guest.py` | Privileged fixture preparation and actual transaction observation after original inner guards. Preserves original initial3354, installed11-file bundle, protected configuration, fixed external/component receipts and the two exact retained probe trees separately. No immutable-root collector over worker output. |
| `tests/test_release_fixture_{data,server,operator}.py` | Portable builders/routes/full-byte TLS, malformed input, auth-client and operator boundary tests. Not simulated installed acceptance. |

Normal0.1.1 and normal0.1.2 change only `VERSION`. The separate negative0.1.2
adds a recorded `SystemExit(73)` at the copied migration CLI entry; migration
tables, contract/schema declarations and installed privileged helpers stay intact.
Checksum rejection uses the unchanged normal0.1.2 archive and a wrong sidecar.
The original complete requirements and their SHA remain unchanged.

### Static original-builder qualification, not a production fix

The exact2dc builder excludes `tests/`, but still packages its **pre-existing**
`scripts/nested_acceptance.py`, `scripts/nested_systemd_fixture.py` and
`scripts/run_nested_systemd_acceptance.py`. The new fixture/operator/server code,
wheelhouse, private proofs, receipts and keys are not in any release archive.
Silently filtering the old scripts would contradict the required real-builder /
VERSION-only source delta. Independent review must resolve this original-source
content against the design's no-test-harness intent; it has not been fixed or
relabeled as accepted. This does not prevent reviewing the implemented commands.

## Local commands and prepared artifacts

Portable build only, into an **absent** output directory:

```powershell
python -B -m scripts.release_fixture_data --output NEW_DIRECTORY --wheelhouse LOCAL_READONLY_WHEEL_SNAPSHOT
python -B -m scripts.release_fixture_operator --help
```

The private locally prepared `wsl-acceptance/f1/` has a complete38-file fixture
map, all29 original wheels (6,967,956 bytes), and all three real source artifacts.
All wheel names/sizes/hashes match the original pinned read-only wheel receipt,
not a newly adopted guest inventory. The source and archive member maps, complete
delta maps and sidecars remain in its manifest. This is **prepared pending
independent review**, not an approval/enrollment record.

| Artifact | SHA-256 |
| --- | --- |
| normal0.1.1 | `001c0bff5123b8b61efd8b7e862cc9382815dbf2dc62436f2ba937375365ff1a` |
| normal0.1.2 | `69c9a77236830f263e61b09caed4674509904fef22a28ca886cf6fb865a4ffcf` |
| migration-negative0.1.2 | `cdac1b6a438246eade32221b0d51ed11de6e4df5766f3b294c1d1e888dcab2d5` |
| whole `fixture.json` | `3eb2bb39c29186c78e58d46f63a5f58e372c035fa4470bccc72f801d6ca7597d` |
| four-module operator code map | `bb4f98da56ff181cbfed42571431fa667941a85ce204201ad4d544b7d64585b9` |

The operator code-map digest covers the sorted JSON map of the four source-file
SHA-256 values, not the current Git HEAD or an observed-state checkpoint. Review
those actual bytes independently before using a pin as an authorization input.

## Future runtime command contract — NOT EXECUTED

Each invocation requires a new exclusive evidence directory and a separate human
authorization for **that phase only**. The matching CLI flags are a safety check,
not a substitute for that authorization. The private original receipts/approvals
are read from the existing fixed acceptance scratch path; there is no alternate
distribution, host, guest, current version, certificate policy or force option.

Example command shape, to be used **only after independent review and a separate
explicit prepare permission**:

```powershell
python -B -m scripts.release_fixture_operator `
  --phase prepare-fixture --authorize-phase prepare-fixture `
  --code-sha256 bb4f98da56ff181cbfed42571431fa667941a85ce204201ad4d544b7d64585b9 `
  --fixture-root wsl-acceptance/f1 `
  --fixture-sha256 3eb2bb39c29186c78e58d46f63a5f58e372c035fa4470bccc72f801d6ca7597d `
  --evidence-dir NEW_PRIVATE_PREPARE_EVIDENCE_DIRECTORY
```

The only phase values are, in strict order:

1. `prepare-fixture`: original runtime/seed/package/CA admission, private-root
   source-verified copies of trusted server/data/artifacts/full wheel bytes;
   inner-only CA/key/certificate, five exact loopback hosts names, and own fixed
   `knxoh-release-fixture.service` on127.0.0.1:443. Saves original hosts/system CA
   bytes and identities and the absence of own CA/unit. Refuses unknown existing
   state or foreign bind mounts. Starts only this fixture unit, not an app unit.
   Actual stdlib and actual seed's no-argument default `PipSession()` must verify
   GitHub/PyPI TLS and reject wrong-host/untrusted-chain controls. The latter uses
   a temporary high-port inner-loopback endpoint and a separate untrusted cert.
   No pip install, pip cache/config/argv/trust override, or application update.
2. `stable-update`: separately permitted only after preparation passes. Rechecks
   original provider/guest/source/installed/protected state and actual TLS;
   authenticates with the original protected root login receipt and actual
   cookie/CSRF flow. Sends one real no-body default-stable POST. Observes the same
   request file/ack/root journal, actual sudo fixed-unit start, unit invocations,
   all five stages, live network/mount namespaces, teardown, notify/health0.1.1,
   final-path venv and the installed full original dependency closure/source bytes.
3. `no-update`: real new UUID and metadata stage only. Requires the actual
   no-newer-release acknowledgement and terminal protected journal, no archive,
   candidate, current/config identity change or app-unit restart.
4. `checksum-rejection`: root selects normal0.1.2 + exact wrong sidecar. Requires
   actual metadata/download success, exact protected archive and worker sidecar,
   terminal protected rollback and unchanged healthy0.1.1/config/current/app units.
5. `migration-rejection`: root selects the separate negative0.1.2. Requires the
   real full venv/preparation and failing migration, terminal protected rollback,
   healthy0.1.1 and production removal of its own failed candidate. No manual
   deletion, current switching, helper replacement or repair is performed.
6. `retry`: root selects normal0.1.2 and requires a fresh UUID through the same
   actual authenticated API/coordinator path, then full successful0.1.2 evidence.

For later phases use the same command options/pins with **both** phase flags set
to the individually authorized phase and a new evidence directory. Do not run
them as an automatically authorized loop. A concurrent POST409 is asserted only
after a protected active transaction/unit is observed, never by forced race/reset.
A lost HTTP response causes observation of the known request, not resubmission.
Own exclusive attempt/result files prevent automatic phase replay; they are not
new baseline approvals. Unknown extra release/preparation/data entries refuse.

All actual fixture effects are limited to the originally owned inner guest. No
Windows/outer-WSL trust/hosts, host Ubuntu, outbound network, dependency upgrade,
production source/helper changes, reset-failed, boot/corrupt-journal testing,
adoption/wipe/force or automatic failure repair/cleanup exists in this CLI.
On failure retain the original journal/candidate/workspaces and private evidence.

## Verification and limits

- Portable TDD RED/GREEN covered the new builders/server and guard behavior,
  including malformed/incompatible wheels, raw `//` request aliases, original
  wheel pins, unknown parent entries and UUID validation before path use.
- Final bounded related native suite: **396 passed,74 skipped** (Windows3.11;
  skips are native symlink/Linux/root/opt-in conditions). Includes real verified
  temporary TLS transfer of all29 complete exported wheels and actual hostname /
  untrusted-chain rejection, without system trust/DNS writes.
- Focused actual Ubuntu3.12.3 run: **52 passed,3 deselected**, using exclusive own
  private test files, the already installed test interpreter and original guarded
  read-only wheelhouse. Git release-build tests were deliberately not run there.
  This run installed/built no packages or releases and used no app/HTTPS unit or
  system trust changes. Temporary HTTP client tests are not installed API proof.
- Black, isort and flake8: **all164 tracked-plus-new Python files passed**.
  `git diff --check` passed. No UI/production changes; no screenshot requirement.
- Full/default native core/UI suites were deliberately not collected under this
  dispatch. No full guest resolver/venv/update/rollback/retry/boot result is claimed.

Raw commands/results and the incremental handoff are private in
`wsl-acceptance/release-fixture-verification.json` and
`wsl-acceptance/release-fixture-implementation-report.md`; original private
read-only/run evidence stays under the existing `.superpowers/sdd/...` scratch.
No private proof, receipt, raw operational log, wheel ZIP or key is committed.
Independent review is still pending. Actual guest trust/TLS/install/update and
the full Task9/parent installed acceptance remain **OPEN**.
