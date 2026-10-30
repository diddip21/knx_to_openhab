# Offline probe source-contract repair — 2026-10-30

**Runner contract fixed offline; hostile runtime acceptance remains NOT VERIFIED.**

This addresses the pre-transport blocker recorded in
`2026-10-30-probe-source-contract-blocker.md`. Both controller program generation
and the guest probe now use the same probe-only selector in
`scripts/nested_fixture_repair.py`. The controller transports that exact current
module in memory rather than relying on the older installed harness copy.

The repaired-source branch calls the existing `validate_repair_source` parser:
purpose `reviewed-environmentfile-fix-source`, production base
`47e2c3a3cd59d716f793226ec17badde60999eca`, complete original baseline and only
the three reviewed delta paths. The original baseline is reconstructed as
hash-only comparison data (two historical entries restored, the added regression
removed) and authenticated by the existing complete baseline-map/archive pins.
It is not a collected checkpoint, a new approval, or an installation-state adoption.
The caller's manifest and all on-disk manifests remain unchanged.

Probe additionally requires exact repaired production HEAD
`2dcf3078b61283a41fd1ef38e34327e4f759d5c1`, canonical 247-file map SHA-256
`e8272d16c145e963bcae7e8c2a9fcb2f5e562a71cd1240de6d6fd054feed4611`, and the
original repaired archive hash. The CLI's existing externally supplied raw manifest
SHA-256 check remains mandatory. The adopted raw approval pin remains
`90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea`.
The guest calls the existing `verify_repair_sources` function, including actual
baseline AND repaired source enumeration, ownership, modes, hashes and VERSION
checks, before loading worker-policy code.
Legacy sudo-source selection retains its original strict parser; there is no
generalized purpose union or `review_approved` shortcut.

Offline regression first reproduced the exact reported failure at
`run_nested_systemd_acceptance.py:118` / `nested_fixture_state.py:405`, then passed
with the unchanged approval. Tests cover both boundaries, rejected purpose/base,
short/mismatched/full runner HEAD, unrelated delta, unreviewed allowed-path blob,
mode, extra/deleted files, archive, non-boolean approval, bad raw manifest pin,
and actual hash-check refusal against synthetic tampered baseline/repaired guest
files. Existing provider, exact-path, preparation and worker/sudo guard ordering is preserved.
Public tests reconstruct the hash-only approval from historical Git blobs and
assert its byte-identical raw SHA; they do not depend on private scratch files.

No production code, provider policy, approval, checkpoint, bootstrap, resume,
readiness behavior, installed fixture, hostile callback or SystemdAdapter changed.
No guest transport, guest app command, probe attempt, service operation or retry
was performed. UI/timer/PID state has not been re-observed. Sandbox/NNP/namespace,
worker denials, installed worker execution, heartbeat and whole-cgroup teardown
remain **NOT VERIFIED**; parent Task5 remains open. Independent review and explicit
controller authorization are required before any next runtime attempt.
