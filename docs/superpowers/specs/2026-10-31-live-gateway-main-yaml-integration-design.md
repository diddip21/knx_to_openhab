# Live KNX gateway integration with current openHAB YAML architecture

## Intent

Reconcile the live gateway IP/Undo feature from PR #55 with current `main`, which
now owns complete-model YAML output. The user chose to keep `main`'s
`output_format` architecture and its openHAB 5.2 YAML contract. DSL/legacy output
remains the default. The separate Things-only YAML selector from the old feature
branch is not retained.

## Goals

- Merge the gateway live-state, apply, ETS-reset, and one-level Undo behavior
  into current `main` without replacing its full-model YAML renderer or output
  migration flow.
- Resolve the active live target from the most recent successful deployment,
  not pending settings: `things_path` for legacy DSL and `yaml_path` for the
  complete YAML model.
- Record deployed output identity, including a unique `deployment_id`, deployment
  `job_id`, root, format, and managed relative path. A deployment to the same
  path—even a redeploy of the same job with identical file bytes—still invalidates
  an earlier Undo snapshot.
- Allow live edits only to the bridge settings in that deployed file and the
  saved gateway override. Never reprocess ETS, restart OpenHAB, call its REST
  API, or claim runtime success.
- Keep Undo durable and one-level, restoring only the previous deployed model
  file and saved override. Refuse without writes if deployment/job identity,
  path/format, or post-change SHA-256 no longer matches.
- Require a known installed OpenHAB version of 5.2 or newer for YAML live
  operations, matching current `main`'s YAML output contract. Mirror the gate
  in the Devices UI.
- Preserve current `main`'s managed-file provisioning, model retirement,
  rollback, and path-validation protections.

## Non-goals

- Do not keep two independent YAML generators or output selectors.
- Do not change current `main`'s YAML document schema, model validation, or
  generated Items/Sitemaps.
- Do not restore the earlier 5.0 Things-only YAML compatibility promise; it is
  superseded by the user-selected current-main architecture.
- Do not fold the separately reviewed gateway-state/ETS-source read timing
  improvement into this conflict-reconciliation scope.

## Approaches

1. **Adopt current `main`'s full-model YAML and port live gateway behavior —
   selected.** Reuse `output_format` (`legacy`/`yaml`), `openhab_yaml.py`, and
   current deployment migration/provisioning. Translate deployed `legacy` to
   the gateway editor's DSL mode and edit the existing bridge mapping in either
   the `.things` file or complete YAML file. This avoids duplicate formats and
   respects the repository's current output contract.
2. **Keep the old Things-only YAML as a second output mode.** Give it separate
   config keys, target path, deployment metadata, UI controls, and migration
   rules alongside current `output_format`. This preserves its OpenHAB 5.0
   target but adds overlapping YAML targets and two competing format lifecycles;
   it is more complex and the user did not select it.

## Design

### Deployment metadata and live target

During staging, record the selected `output_format`, normalized gateway format
(`dsl` for `legacy`, otherwise `yaml`), the selected managed relative file path,
the OpenHAB root, and the deployed job ID. Each successful deployment also gets
a unique `deployment_id`; older jobs without one use a stable job/time fallback
for target identity. Preserve the existing latest-successful deployment
resolution and fail closed when metadata is absent or the path is not in that
deployment's managed targets. Pending `output_format` or `yaml_path` changes must
not relabel or retarget the live controls.

### File transformations and Undo

Keep the current safe DSL bridge editor. Reuse the YAML bridge mapping shape
emitted by `openhab_yaml.new_model()` to edit only
`things["knx:ip:bridge"].config` in a full YAML model, preserving the remaining
document. Serialize reads/writes, configuration changes, deploy, and Undo with
`JobManager.operation_lock`.

Before apply/reset, atomically persist a schema-v2 snapshot containing the
previous file bytes and gateway override plus the deployed `deployment_id`, job
ID, root, managed path, normalized format, and expected post-change digest. Undo
checks all target identity fields and the digest before any write, restores only
the file and override, and consumes the snapshot only after success. Legacy v1
snapshots remain readable but lack a deployment identity and cannot be used for
Undo. A new deployment to the same target invalidates the v2 snapshot.

ETS reset uses the detected gateway address recorded by the latest successful
ETS deployment. If that deployment has no recorded gateway source, reset is
unavailable; if it has a source but no detected IP, reset selects KNX router
mode and clears the saved override. An invalid detected address fails before
writing. If an apply/reset/undo operation partially fails, compensate by
restoring both file and config state; preserve the previous Undo snapshot unless
Undo completed successfully. Report compensation failures rather than claiming
success.

### YAML compatibility and provisioning

Use current `main`'s known local OpenHAB version source. YAML apply/reset/Undo
are rejected server-side unless the version is known and at least 5.2; UI
controls mirror the result. Keep existing YAML-path provisioning through the
fixed privileged helper and preserve rollback if provisioning fails. Do not
create managed output files as part of deployment or live edits.

### UI and documentation

Keep current `main`'s `conf-output-format` selector and YAML path control; do not
add a second Things-format selector. Add the live target/status, apply, ETS
reset, and Undo controls to the Devices view. Display only the relative path of
the last deployed target. Disable all actions when target metadata is unusable
or YAML compatibility is not confirmed; enable Undo only when the server says
the snapshot is available. Re-capture the two committed UI screenshots against
the merged UI and update the user guide to describe complete-model YAML on
OpenHAB 5.2+ and file-only live actions.

### Test coverage

- Adapt gateway backend tests to `output_format`, full-model YAML fixtures, and
  deployed target metadata; retain regression coverage for intervening deploys,
  same-job/same-target redeploys with identical bytes, changed file bytes,
  compensation, and no network/REST behavior.
- Keep current `tests/test_openhab_yaml.py` and output migration tests as the
  source of truth for complete-model YAML; remove obsolete Things-only renderer
  tests and avoid duplicate format migration logic.
- Adapt UI tests to `conf-output-format`; cover deployed target display, target
  unavailability, YAML 5.2 version gating, apply/reset/Undo, and runtime-unchecked
  feedback.
- Run focused gateway/output tests, full core and UI suites, formatting/lint,
  compile/syntax checks, and `git diff --check` before updating PR #55.

## Compatibility

The externally visible default remains legacy DSL. Existing current-main YAML
output and migration behavior remain authoritative; YAML live actions follow its
OpenHAB 5.2 minimum. Older deployed jobs without an explicit safe target remain
ineligible for live edits rather than falling back to pending config paths.
