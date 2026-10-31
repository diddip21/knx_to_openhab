# Live KNX Gateway Integration with Current YAML Architecture — Implementation Plan

> **For the implementer:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and execute this plan inline, task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR #55's live KNX gateway IP and guarded Undo behavior with current `main`'s complete-model YAML output, keeping DSL/legacy as default.

**Architecture:** Keep `output_format` (`legacy`/`yaml`) and `openhab_yaml.py` as the only output-format system. Normalize deployed `legacy` to DSL for bridge-file editing; resolve live targets from successful deployment metadata and edit the deployed `.things` or complete YAML file in place. Persist one-level Undo bound to unique deployment ID, deployment job ID, managed target, and post-change digest; require known OpenHAB 5.2+ for YAML actions.

**Tech Stack:** Python 3.12+, Flask, vanilla JavaScript, PyYAML, pytest, Playwright, Git merge/review tooling.

**Spec:** `docs/superpowers/specs/2026-10-31-live-gateway-main-yaml-integration-design.md`

## Global Constraints

- Current `main`'s complete-model YAML renderer/schema/migration remain authoritative; do not keep the branch's separate Things-only YAML output selector.
- Legacy DSL remains the default; YAML live operations require a known installed OpenHAB version >= 5.2.
- Live operations target the latest successful deployment, never pending config, and fail closed if safe deployment metadata is unavailable.
- Undo restores only the previous deployed model file and saved gateway override; any new deployment identity, target change, or file digest change makes it stale.
- Live operations do not reprocess ETS, restart OpenHAB, call its REST API, or claim runtime success.
- Preserve main's protected YAML provisioning, model retirement, rollback, managed-file, symlink, and hard-link protections.
- Re-capture genuine anonymized UI screenshots after the UI integration.

## Review Focus

- **Complete YAML document preservation:** live bridge edits must leave YAML Items, Sitemaps, and other Things unchanged; test in Task 3.
- **Legacy/deployed jobs without explicit output target metadata:** do not infer from pending config; disable/reject live operations; test in Task 2.
- **Same-path redeployment with identical bytes:** the changed deployed job ID invalidates Undo; test in Task 3.
- **OpenHAB YAML version 5.1.x or unknown:** block backend and UI YAML actions; 5.2+ is allowed; test in Tasks 3–4.
- **ETS source with no detected IP or invalid data:** router mode/reset availability and no-write behavior remain deterministic; test in Task 3.

---

### Task 1: Resolve generator and configuration conflicts in favor of current `main`

**Files:**
- Modify: `config.json`
- Modify: `web_ui/backend/config_schema.json`
- Modify: `ets_to_openhab.py`
- Modify: `docs/USER_GUIDE.md`
- Preserve/refactor as needed: `web_ui/backend/things_format.py`, `knx_things.py`
- Test: `tests/test_output_config.py`
- Test: `tests/test_openhab_yaml.py`
- Replace obsolete coverage after gateway helper migration in Task 3: `tests/test_knx_things.py`, `tests/test_things_format_jobs.py`

**Interfaces:**
- Keep `output_format` values `legacy` and `yaml`; `legacy` is the default. YAML continues to use `yaml_path` and the full `version: 1` model (`things`, `items`, `sitemaps`) from `openhab_yaml.py`.
- Retain a small mapping from normalized gateway format (`dsl`/`yaml`) to `things_path`/`yaml_path` for live-file operations; do not add a second persisted format selector.
- `ets_to_openhab.main(configuration=...)` continues returning `{"things": <legacy text>, "yaml_model": <mapping or None>}` for the job manager.

- [ ] **Step 1: Add/adjust tests for the authoritative format configuration**

Assert a missing `output_format` defaults to `legacy`, the schema exposes only `legacy`/`yaml`, and a YAML run still renders the full openHAB model with the KNX bridge/device and existing Items/Sitemaps.

- [ ] **Step 2: Run the focused tests and verify failures**

Run: `python -m pytest tests/test_output_config.py tests/test_openhab_yaml.py -q -o addopts= --tb=short`

Expected: tests fail only where merged files still contain the separate `things_format` architecture or unresolved conflict markers.

- [ ] **Step 3: Resolve `config.json`, schema, and generator conflicts**

Keep main's `sitemap_label`, `output_format`, and full-model YAML pipeline. Remove the competing `things_format` config/schema and `KnxThingsModel` render path. Retain current-main completeness-report behavior and preserve gateway detection/template rendering for legacy DSL.

- [ ] **Step 4: Audit references and defer helper cleanup until gateway migration**

Confirm the generator no longer imports the old Things-only renderer. Keep `things_format.py` and `knx_things.py` temporarily because live gateway/jobs still depend on their format selection, inactive-file, or YAML-channel helpers. Task 3 will remove obsolete Things-only renderer code/tests after Tasks 2–3 migrate those callers; preserve the unmanaged-bridge scan with focused coverage.

- [ ] **Step 5: Run output/generator tests**

Run: `python -m pytest tests/test_output_config.py tests/test_openhab_yaml.py tests/test_deploy_policy.py -q -o addopts= --tb=short`

Expected: current-main legacy/YAML generation, migration, and managed-path tests pass.

Keep the in-progress merge as one merge commit after all conflict resolution and verification; do not create intermediate commits while this merge is open.

### Task 2: Bind deployment metadata and live target to `output_format`

**Files:**
- Modify: `web_ui/backend/jobs.py`
- Modify: `web_ui/backend/gateway_config.py`
- Modify: normalized-format helper retained from Task 1
- Test: `tests/test_gateway_live_update.py`

**Interfaces:**
- `JobManager.get_last_deployed_things_target() -> dict[str, str] | None` returns `deployment_id`, `job_id`, `openhab_root`, `managed_path`, `output_format`, and normalized `things_format` (`dsl` or `yaml`). Older safe deployment records get a stable job/time identity fallback.
- Staged/deployed jobs record both main's `output_format` and the active managed relative path in `active_things_path`, alongside `openhab_root` and `managed_targets`.
- Jobs with missing/untrusted target metadata return no target; live actions never fall back to config paths.

- [ ] **Step 1: Add failing tests for legacy/YAML deployment metadata and fail-closed lookup**

Cover latest deployed legacy and YAML targets when pending config differs, staged jobs being ignored, old deployed metadata without an active target being unavailable, and staged-job format/path metadata.

- [ ] **Step 2: Run target tests and verify failure**

Run: `python -m pytest tests/test_gateway_live_update.py -k 'last_deployed' -q -o addopts= --tb=short`

Expected before conflict resolution: test collection stops at the unresolved `jobs.py` merge marker. After resolving that syntax conflict, the target assertions are rerun and must cover both output formats, missing metadata, and staged-job exclusion.

- [ ] **Step 3: Record and resolve output target during job staging**

Use main's staged output selection: `things_path` for `legacy`, `yaml_path` for `yaml`; record normalized gateway format and active managed relative path. Keep main's retired-output mapping and rollback intact. Retain duplicate-bridge detection when switching model formats.

- [ ] **Step 4: Implement latest deployed target resolution and gateway state against that target**

Revalidate root/path with `configured_managed_paths()`. Add target `deployment_id` and `job_id` to the identity consumed by Undo. Ensure Gateway state reports a relative managed path and no runtime status other than `not_checked`.

- [ ] **Step 5: Run focused target and API tests**

Run: `python -m pytest tests/test_gateway_live_update.py -q -o addopts= --tb=short`

Expected: all target/state tests pass, including missing metadata and pending-format mismatch.

### Task 3: Integrate file-only gateway actions, OpenHAB 5.2 gate, and guarded Undo

**Files:**
- Modify: `web_ui/backend/jobs.py`
- Modify: `web_ui/backend/gateway_config.py`
- Modify: `web_ui/backend/gateway_undo.py`
- Refactor/remove: `web_ui/backend/things_format.py`, `knx_things.py`
- Test: `tests/test_gateway_live_update.py`
- Replace obsolete tests: `tests/test_knx_things.py`, `tests/test_things_format_jobs.py`

**Interfaces:**
- Keep `apply_gateway_ip(ip)`, `restore_gateway_ip()`, and `undo_gateway_ip()` serialized by `operation_lock`.
- YAML edits target only `things["knx:ip:bridge"].config` in the complete model, preserving all other sections.
- Persist schema-v2 snapshot fields: `deployment_id`, `job_id`, `file_content_b64`, `previous_gateway_override`, `openhab_root`, `managed_path`, normalized format, and `post_change_sha256`. Legacy v1 snapshots remain readable but are stale for Undo.

- [x] **Step 1: Add regression tests for full-document preservation and YAML 5.2 gating**

Test that apply/reset alter only the bridge config while preserving Items/Sitemaps and other Things. Parametrize backend gate for 5.1.x, unknown, malformed, and 5.2+ for apply/reset/undo. Also verify deploy blocks known versions below 5.2, and Undo snapshots require deployment and job identities.

- [x] **Step 2: Add/retain Undo tests for same-target redeployment, external edit, and compensation**

Assert redeploying the same job invalidates a snapshot even when root/path/format/file bytes match; each successful deployment receives a new `deployment_id`. Stale attempts do not write and retain the snapshot. Assert partial failures restore both file/config and prior snapshot.

- [x] **Step 3: Run gateway regression tests and verify failures**

Run: `python -m pytest tests/test_gateway_live_update.py tests/test_things_format_jobs.py -q -o addopts= --tb=short`

Observed: the live gate tests rejected 5.0/5.1 incorrectly, the snapshot schema accepted a missing `job_id`, and YAML deployment bypassed the 5.2 check because deploy read the retired `things_format` metadata; all failed before the corresponding fixes. Complete-model equality passed against the preexisting safe bridge editor.

- [x] **Step 4: Port the bridge editor and Undo guards**

Retain safe DSL parsing and the existing complete-model YAML editor, verified by equality regression tests. Require a known `>= 5.2` version before YAML apply/reset/Undo and deployment. Require deployment and job IDs in the Undo snapshot and compare them with the active deployment.

- [x] **Step 5: Run the focused gateway suite**

Run: `python -m pytest tests/test_gateway_live_update.py tests/test_gateway_ip.py tests/test_deploy_policy.py tests/test_things_format_jobs.py tests/test_openhab_yaml.py tests/test_output_config.py -q -o addopts= --tb=short`

Result: 145 passed, 4 skipped.

### Task 4: Merge config API and Devices UI without duplicate format controls

**Files:**
- Modify: `web_ui/backend/app.py`
- Modify: `tests/test_web_ui_job_endpoints.py`
- Modify: `web_ui/templates/index.html`
- Modify: `web_ui/static/app.js`
- Test: `tests/ui/test_gateway_live_update.py`
- Test: `tests/ui/test_output_format_config.py`

**Interfaces:**
- Keep the existing `POST /api/gateway/ip`, `/reset`, and `/undo` routes and `GET /api/gateway/state`; keep the current `POST /api/config` YAML provisioning behavior.
- UI reads main's `conf-output-format`; live target display is based only on `/api/gateway/state` deployed metadata.
- All live actions are disabled when no deployed target exists or a YAML deployed target has unknown/older-than-5.2 OpenHAB; Undo additionally requires `undo_available`.

- [x] **Step 1: Add failing config/API and UI tests for preserved provisioning and live controls**

Assert config save retains main's YAML-path provisioning/rollback under `operation_lock`, live API routes retain file-only feedback, and the UI uses `conf-output-format` while pending selections do not relabel the deployed target.

- [x] **Step 2: Run focused API/UI tests and verify failures**

Run API tests: `python -m pytest tests/test_web_ui_job_endpoints.py -q -o addopts= --tb=short`

Then prepare the isolated UI test environment using the setup steps in `.github/workflows/ci.yml` (including `tests/ui/setup_test_env.py`) and run: `python -m pytest tests/ui/test_gateway_live_update.py tests/ui/test_output_format_config.py -v -m ui --tb=short`. Check for and remove test-only config/data changes before committing.

Observed: pre-resolution API collection was blocked by the existing `app.py` conflict markers; after resolution, provisioning/rollback and lock tests passed. UI tests exposed a duplicate function declaration that shadowed the warning handler and an over-specific readiness assertion tied to non-empty legacy paths.

- [x] **Step 3: Resolve app config-save conflict**

Combine operation-lock serialization with current-main YAML provisioning and rollback. Preserve provisioning when only `yaml_path` changes and do not lose sibling config keys.

- [x] **Step 4: Merge UI state, controls, and events**

Retain main's output-format/path selector and wire gateway controls into the same Devices pane. Show deployed path relative to OpenHAB root; retain explicit runtime-unchecked success/error copy. Remove obsolete duplicate Things-format control.

- [x] **Step 5: Run focused UI/API tests**

Run API tests: `python -m pytest tests/test_web_ui_job_endpoints.py -q -o addopts= --tb=short`

Then run the focused UI tests in the prepared Playwright test environment: `python -m pytest tests/ui/test_gateway_live_update.py tests/ui/test_output_format_config.py -v -m ui --tb=short`. Check for and remove test-only config/data changes before committing.

Result: API tests 29 passed; focused UI tests 14 passed, including YAML 5.2 boundary and Undo.

### Task 5: Reconcile documentation, screenshots, and complete verification

**Files:**
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/screenshots/knx-gateway-live-ip.md`
- Update: `docs/screenshots/knx-gateway-live-ip-settings.png`
- Update: `docs/screenshots/knx-gateway-live-ip-applied.png`
- Resolve and commit: all merge-conflict files

- [x] **Step 1: Merge current-main YAML documentation with gateway instructions**

Document the full openHAB 5.2 model, legacy DSL default, deployed-file live target, 5.2 compatibility gate, pre-provisioned managed targets, one-level Undo safeguards, and runtime-unchecked behavior.

- [x] **Step 2: Recapture screenshots from the merged UI**

Use the real Flask UI with isolated API fixtures and reserved documentation IPs. Show `output_format`, deployed relative path, Apply, and Undo; verify no temporary paths, secrets, or personal data.

- [x] **Step 3: Run complete checks**

Run the full core suite on the CI Python 3.12/3.13 matrix (`pytest -q --cov=. --cov-report=xml -m "not ui" --ignore=tests/ui`), the full Playwright UI suite on CI's Python 3.12/Linux setup (`pytest tests/ui/ -v -m ui --tb=short`), and CI lint (`black --check .`, `isort --check-only .`, `flake8 .`, `mypy .`). Also run `node --check web_ui/static/app.js`, `python -m compileall -q web_ui/backend`, and `git diff --check`. Run checks locally where available and report the CI-only checks without claiming they ran locally.

Result: Python 3.12.3 on WSL/Linux — core 551 passed, 11 skipped; UI 125 passed, 2 skipped; Black, isort (excluding the local virtual environment), Flake8 (excluding local environments), mypy, JavaScript syntax, backend compileall, and `git diff --check` passed. Python 3.13 remains CI-only.

- [ ] **Step 4: Review merge result and commit**

Confirm no conflict markers remain, `git diff origin/main...HEAD` contains only intended feature behavior beyond current main, and protected current-main changes remain. Commit the merge resolution on `feat/knx-gateway-main-reconcile`.

The first fresh review identified two issues. The same-job redeployment finding was verified and fixed by persisting a unique deployment identity. The ETS-source read-race suggestion was left unchanged because this design explicitly excludes that separately reviewed timing improvement (Non-goals, lines 41–42); it remains outside this reconciliation.

- [ ] **Step 5: Update PR #55**

Fast-forward the PR head `feat/live-knx-gateway-ip-dsl-yaml` to the verified merge commit without force-push. Update the PR body with final behavior and test results. Preserve its current Draft status; changing review status requires separate user approval.
