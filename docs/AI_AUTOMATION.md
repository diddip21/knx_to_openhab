# Generic owner-approved AI workflow

This is repository tooling, not application runtime code. No controller contains
an issue number, HomeKit prompt, fixed plan version or per-feature write list.
The old issue-specific executables, agents and duplicate guard workflows have
been removed.

## Activation and migration

Review the infrastructure PR and its complete CI before manually merging it into
`main`. The issue-comment and workflow-run controllers live on this default
branch. Then synchronize the reviewed `main` into `dev`, preserving existing
work. No controller merges either branch. The shared CI definition and OpenCode
policies on `dev` must match trusted `main` before generation can start.

The hardware-gate removal from #116 is included in this generic implementation.
Do not reintroduce the old readiness script by resolving a merge conflict in
favor of the retired controller. Application PR #108 is not rewritten or merged.
Its old command has no explicit file scope and is NOT silently upgraded to the
new authorization protocol. Use a new approved plan for a fresh test run; retain
#108 as a comparison until the owner decides what to do with it.

## Bedienung: Plan freigeben und Umsetzung starten

Owner-Kommentare mit `/ai ...` erhalten eine **👀-Reaktion**, sobald der separate
Empfangsjob startet. Das bedeutet **„Befehl empfangen“**, auch wenn später noch
eine Prüfung fehlschlägt; es bedeutet keine Freigabe oder erfolgreiche Ausführung.
Der Empfang läuft unabhängig von Modell, `main`/`dev`-Prüfung und CI. GitHub kann
den Job zunächst in eine Warteschlange stellen. Normale Kommentare und fremde
Autoren erhalten keine Bot-Reaktion; Wiederholungen desselben Jobs duplizieren
die Reaktion nicht. Ergebnisse und nächste Schritte stehen im Bot-Status.

| Schritt | Was du bestätigst | Neuer Issue-Kommentar | Was danach passiert |
|---|---|---|---|
| Plan anfordern | Die KI soll einen Vorschlag erstellen | Label `ai:plan` setzen | Read-only Prüfung von `dev` und bestehenden offenen PRs |
| Plan korrigieren | Anforderungen oder Dateiliste ändern | `/ai answer DEIN HINWEIS` | Neuer Plan; alte Freigabe gilt dafür nicht |
| Plan freigeben | Ziel, Vorgehen und angezeigter Dateiumfang passen | `/ai approve vN` | Bot bestätigt die Freigabe und zeigt den Startbefehl |
| Umsetzung starten | Jetzt genau diesen Plan im angezeigten Dateiumfang ausführen | `/ai start vN` | Modelllauf, Prüfung, Formatierung, Draft-PR und CI |
| Merge entscheiden | Aktuelle CI, Screenshots und Review sind geprüft | GitHub-PR bewusst mergen | Eigene menschliche Entscheidung |

`N` ist die konkrete Versionsnummer im Bot-Kommentar, etwa `v4`. Jeder Befehl
gehört in einen **neuen Kommentar**. Bearbeiten eines alten Kommentars startet
keinen Lauf. `approve` startet keine Codeänderung. Erst `start` autorisiert die
Umsetzung samt der im unveränderten Bot-Plan hinterlegten Dateiliste.
Du musst bei neuen Plänen keinen JSON-Block kopieren. Der Bot validiert die
vorgeschlagene Liste vor Veröffentlichung; die Owner-Befehle verleihen die Rechte.

Der kurze Start gilt nur für neue Pläne mit strukturiertem Dateiumfang. Bei
älteren Plänen bleibt `/ai implement vN` mit vollständigem JSON-Block gültig.
Ein alter Plan wird nicht automatisch auf den kurzen Start umgestellt.

Ein neuer, nicht leerer Owner-Kommentar `/ai answer ...` sperrt die alte
Freigabe sofort für Umsetzung und Reparatur, auch wenn die neue Planung später
fehlschlägt. Vor dem Modelllauf entfernt der Planer `ai:approved` und setzt
`ai:waiting`. Ein erneutes `approve` für den alten Plan hebt diese Sperre nicht
auf; nötig sind ein neuer Plan sowie dessen Freigabe und Start. Ältere laufende
Planungen dürfen neuere oder geänderte Anforderungen nicht überschreiben.

## Normal issue-to-PR sequence

1. Describe the task and acceptance criteria; request planning using `ai:plan`.
   The existing read-only planner proposes changes, tests and exact paths.
2. Resolve questions using `/ai answer ...`. Review the current plan and post
   `/ai approve vN`. Wait for the bot's matching approval receipt.
3. For new plans, separately post the short command shown in the bot receipt:
   `/ai start vN`. The immutable bot plan contains the displayed, validated
   `files`/`create`/`required` scope. Both Python and the independent publisher
   bind that scope to the live plan, approval and command hashes.
   For existing legacy plans, post the full command and reviewed JSON scope:

   ````text
   /ai implement vN
   ```json
   {
     "files": ["some_module.py", "tests/test_some_module.py", "docs/USER_GUIDE.md"],
     "create": ["tests/test_some_module.py"],
     "required": ["some_module.py", "tests/test_some_module.py"]
   }
   ```
   ````

   Replace `N` and the example paths. `files` is the complete allowed set;
   `create` authorizes missing files; `required` identifies files that need a
   meaningful task-related change against the original implementation baseline.
   A file's existence alone does not satisfy `required`, and cosmetic dummy edits
   are not a substitute for the approved work. The guard checks for a change;
   its substance still requires review. Empty `create`/`required` lists are allowed.
   Only the repository owner's live, unedited start command grants this scope. A model proposal,
   label, issue body or PR description does not grant write permissions.
4. The read-only generation job selects an approved free model, installs the
   pinned OpenCode CLI and builds literal agent permissions from the owner scope.
   Shell, external directories, Code Mode, network tools and subagents stay denied.
5. Implementation and repair generation jobs select Python `3.12` explicitly before
   running any Python controller. The pinned formatters are installed from the trusted checkout
   with `python -I -m pip --isolated install --no-user`; both formatter modules are
   executed with `-I` before model selection or generation. A missing or inaccessible
   formatter therefore stops the job before model work. User-site packages are not
   a fallback because the isolated formatter intentionally cannot import them.
   Trusted Black `26.10.1` and isort `9.0.2` format only changed approved Python
   files, including tests, with trusted configuration and explicit filenames.
   These versions match CI's development requirements and both generation and
   repair jobs. No candidate code is executed during formatting. Scope,
   file modes, creation rights, sizes and diff budgets are checked again after
   formatting. A separate publisher re-fetches the issue and all authorization comments,
   validates the candidate against trusted Git objects, and creates a Draft PR
   against `dev`. It explicitly dispatches the full existing CI and binds its
   continuation to the returned CI run ID.
6. A failed **dispatched CI** may trigger at most two repairs of the same
   bot-authored, open **Draft** PR, on the exact failed SHA. Repairs cannot add
   files or expand the original owner scope. Normal PR-CI failures, foreign
   repositories, Ready-for-review PRs, stale runs and revoked approval do not
   authorize repair. Manual commits never reset the two-attempt budget.
7. The read-only readiness workflow checks current plan/scope, one exact CI run
   and attempt for the current head, human review, unresolved threads,
   mergeability and UI screenshot files when UI paths changed. It reruns after
   CI completion, PR/review events, and via
   Actions -> AI merge readiness (read-only) -> Run workflow -> PR number.
8. The owner reviews evidence, marks the Draft ready, and merges deliberately.
   Release remains a separate reviewed `dev` -> `main` change.

## Planner diagnostics and bounded retries

Model selection has its own diagnostic artifact,
`ai-model-selection-<run ID>-<attempt>`, uploaded immediately after the router
in planning, implementation and repair, even if no generation begins. It
distinguishes discovery errors, an empty catalog, no approved candidates,
and failed live probes using fixed codes, allowlisted IDs, timings and
counters only. The pinned CLI is queried with `opencode models --standalone`
at most twice; model permissions and the approved allowlist are unchanged.
Selection failure still prevents generation/publication. See
[model router diagnostics](OPENCODE_MODEL_ROUTER.md#failure-diagnostics).

The planner distinguishes provider/CLI failures, timeouts, truncated or empty
output, invalid JSON/schema and invalid scope. A provider error event is a
failure even if the CLI exits zero. Only models that passed this run's approved
free-model probes may be used. A malformed response gets one corrective retry
on the same model, including after a timeout retry if an attempt and time remain.
The rejected text is supplied privately as untrusted data for format correction,
within the existing prompt-size bound. It is never published or uploaded as
diagnostics. The corrected response passes the full JSON, schema and scope checks.
A further failure may use the other successfully probed model. Provider/runtime
failures can move directly to that fallback. All attempts share one explicitly
identified private session and eleven-minute total budget, with at most three
model calls. The first research call can use 570 seconds, reserving time for
continuation or format correction. Research is not restarted after five minutes.
The CLI first receives SIGTERM and eight seconds to interrupt and save its work;
only then may the controller kill its process group. A hard-killed timeout cannot
be resumed. Before continuation, the controller checks the stored session's
directory, model, agent, parent and permission overrides through the pinned CLI's
read-only session API. A missing session fails rather than silently starting over.
Checkout identity, tracked changes, request, policy and collected source files
are bound to the session; any change prevents continuation/publication. The CLI
receives the real checkout as PWD, never an inherited stale directory.
Previous plans and full collected PR snapshots are supplied in a local reference
file rather than repeated in the initial model request. Diffs retain real line
breaks so read-tool line limits do not clip a single JSON-escaped patch line.
Prompt and output sizes are bounded. Invalid or superseded results are never
published as plans, and a failed replan does not restore the old approval.

The `ai-planner-diagnostics-<run ID>` artifact records model IDs, attempt phases,
fixed failure codes, event/size counts and durations; the job summary lists the
attempts and outcome. The artifact is retained for seven days. Raw prompts,
model replies, stderr, tool
outputs and environment values are not uploaded as diagnostics. Use the code
and attempt sequence to distinguish a provider failure from a response that
failed validation; an artifact's existence does not establish a successful plan.

Progress observations are also retained after a timeout: completed reads,
searches, skills, model steps, token counts and provider retry/wait counts.
Text silence alone is not treated as a stall: the pinned CLI emits some text only
after a completed section. Source text, session identifiers and provider messages
remain private. Provider delays cannot be diagnosed from byte counts alone.

### Versioned research evidence and unpublished replay

The controller includes explicitly linked closed/merged PRs as well as related
open PRs. It collects bounded same-repository commit diffs, pinned GitHub files
(full commit SHA or version tag resolved to a SHA), and official openHAB add-on
documentation without passing credentials to those documentation requests or
following redirects. Whole sources are saved as untrusted reference files under
the ignored `.planner-evidence/` directory, outside the prompt-size budget.
Unavailable, oversized, unversioned, incomplete and omitted evidence is identified
in the manifest; it is never silently presented as complete. The agent still
researches affected source and tests and must identify further missing evidence.

For an owner-authored same-repository controller PR, opt into the read-only
`Unpublished planner research replay` workflow with one standalone PR-body marker
`<!-- ai-planner-diagnostic: N -->`, replacing N with the target issue number.
The workflow uses the production prompt and source collector, deliberately
interrupts real research after 90 seconds, verifies the saved session and resumes
it. Success requires a validated plan, completed reads before interruption and
completed reads of every available supplied source across the resumed history.
Reference presence is counted separately and does not prove semantic correctness.
Only numeric/fixed-code diagnostics and the normal model-selection report are
uploaded; the reply and session history stay private. There is no publisher and
no issue, label, approval or PR mutation in this replay. Review the real evidence
before merging a controller change; simulations alone do not establish that the
pinned CLI/provider can preserve research across an interruption.

## Exact CI continuation and recovery

The trusted publisher dispatches `ci.yml` with GitHub API version `2026-03-10`,
uses that response's `workflow_run_id`, and verifies the run's repository,
workflow, branch, SHA and attempt. It then explicitly dispatches
`opencode-ci-self-repair.yml` on the trusted default branch with `ci_run_id`,
`ci_run_attempt` and `ci_head_sha`. Candidate CI retains read-only permissions;
it does not publish code or run a privileged continuation step. The existing
`workflow_run` entrypoint remains supported, but is not the only handoff.

The continuation waits for that exact run, rechecks the current open bot PR,
and starts the read-only readiness audit. A failed current run can enter the
bounded repair path; success proceeds to the human gates. Closed PRs, changed
heads, rerun attempts and newer dispatched runs on the same SHA cannot reuse
older failure evidence. Duplicate continuations are serialized and superseded
sources become no-ops. Dispatch inputs identify evidence, not authorization:
every repair and publication still checks the original live owner approval.

If publication succeeds but continuation dispatch fails, use **Actions ->
AI CI self-repair -> Run workflow**, select the repository's trusted default
branch, and enter the exact `ci_run_id`, `ci_run_attempt` and full 40-character
`ci_head_sha` reported by the publisher. Only the owner or bot may use this
entrypoint. Do not restart implementation or CI to resume this completed
publication. An ambiguous CI dispatch is never retried automatically; inspect
the actual run before recovery. Only transient continuation-dispatch failures
receive bounded automatic retries.

## Unattended generation and repair

Implementation and repair run as already authorized, unattended workers in an
isolated checkout. They create the complete approved patch and end the session.
They do not ask for another confirmation, restart planning, create worktrees,
write task ledgers or make commits. Compatible debugging and TDD principles
remain useful references; interactive skill steps requiring prohibited tools
or extra files do not apply to this worker. Regression tests are designed first;
actual execution belongs to the reviewer and CI. A model must report checks it
could not run, never invent their results.

Both model steps use the trusted `generation_runner.py` with bounded output,
process lifetime and at most two model invocations in total. A successful first
invocation does not require a second one.

Implementation has one narrowly defined completion path: if the first model
process finishes cleanly, all scope, runtime and file-boundary checks pass, and
the remaining failure is `required_missing`, the runner may make one targeted
completion call to the same model that passed this run's router probe. It retains
the checked partial patch and supplies the missing approved paths only as private
prompt feedback. The original plan, approval, allowed paths and budgets remain
unchanged. The completed patch is checked again against the original baseline.
This completion consumes the second invocation; if it fails, the runner stops
without a third invocation or a subsequent fallback to another model. CI repair does
not use this completion path.

For other retryable failures, a fallback is allowed only to another approved
free model that passed the router probe in this same run. A successful probe
from an earlier workflow does not authorize a fallback. If that second verified
model is unavailable, the runner stops with diagnostics. Policy and boundary
violations still stop immediately.

| Mode | First invocation | Second invocation limit | Total model budget | Job limit |
|---|---|---|---|---|
| Implementation | Up to 1,150 seconds | Up to 650 seconds | 1,800 seconds | 40 minutes |
| CI repair | Up to 750 seconds | Up to 250 seconds | 1,000 seconds | 28 minutes |

The second invocation, whether completion or fallback, is also
bounded by the remaining total budget. On the Linux runner, the controller stops
and reaps the attempt's child processes, including
OpenCode's detached standalone server, before inspecting or restoring files.
Children that already existed before the attempt are excluded. Prompts enter
through bounded stdin, avoiding per-argument limits for long UTF-8 input.

Before falling back to another model, the runner restores approved partial
changes to their original baseline. It does not use a blanket reset or clean to hide
foreign changes. Changed HEAD, runtime-agent tampering, out-of-scope paths and
unsafe links stop the run without completion or fallback. Repair still cannot
create new files. The two-invocation model budget is separate from, and does not
increase, the limit of two published CI repairs.

After the model step, including a controlled timeout or failure, the workflow
uploads only `generation-diagnostics.json` as
`ai-generation-diagnostics-<run-id>-<run-attempt>`. The job and step limits leave
time to write and upload this report. It contains fixed result codes, attempt
phases, verified model identifiers, timings, byte/event/tool counters and
candidate-file counts. Missing required paths appear only in private completion
feedback; diagnostics contain their counts, not paths or file contents.
Prompts, source code, tool arguments, raw stderr and provider messages are not
uploaded. Missing or malformed event data is reported explicitly. Runner loss
or a forced infrastructure termination can still prevent an artifact upload;
the GitHub job status must therefore be checked as well.

A successful runner means only that a model candidate was produced. The
existing trusted formatter, bounded artifact collection, independent publisher
revalidation, complete CI and human review remain mandatory. A diagnostics
upload cannot turn failed generation into successful publication. Scope or
authorization violations are not retried by widening permissions.

## Scope and safeguards

Literal ASCII repository-relative paths only; no wildcard, traversal, hidden
path, symlink, hardlink, deletion, rename or binary artifact. Normal application
source, documentation and test paths are supported. Automation, workflow,
installer, dependency, approval-policy and test-harness changes require a
separate human-led infrastructure PR. An owner command cannot override these
controller restrictions. Code changes must include a changed Python regression
test. Documentation-only changes do not need a fabricated test change.

Limits: 20 files, 300 KB per file, 1.25 MB total, 2,500 changed lines initially;
12 files and 650 changed lines per repair; at most two repair commits. The
publisher independently rechecks sizes, file bytes, hashes, original file modes,
new-file permissions, required files and changed-line counts. It never imports
or executes candidate code. Python runs isolated (`-I`) from trusted scripts.
Only trusted publisher jobs may move AI branches, and repair pushes are
fast-forward-only. Routing and status jobs have only their separate, required
Actions or issue permissions and never execute candidate code.

The original command, plan and normalized scope are hash-bound into the PR.
Editing or deleting those comments, changing the issue, replacing the plan,
removing approval, moving a branch, or rerunning CI while repair is in flight
causes a stop instead of a silent pass. A repeat of the same run with an existing
matching PR resumes CI without republishing code. Another PR for the same plan
is rejected. If branch creation succeeds but PR creation fails, inspect the
orphan branch manually; it is never silently overwritten. Concurrent manual
administrator mutations cannot be made transactional with separate GitHub API
calls; publication rechecks immediately before ref changes and fails closed
where a mismatch is observed.

No hardware test is required by software readiness. No real-device behavior is
claimed as validated by CI. Screenshot file presence is not proof of image
content: human visual review is still required. A successful model run is not a
test result. Tests and source still need independent review; a model can propose
incorrect behavior even within an authorized file list.

## Rückmeldungen und bestehende Arbeit

Ein Bot-Statuskommentar pro Startauftrag wird aktualisiert: Veröffentlichung,
PR/SHA, laufende oder abgeschlossene CI, Reparaturzähler und nächster Schritt.
Fehler beim Start oder bei der Reparatur werden mit Run-Link und Schrittnamen
gemeldet; rohe Modelltexte und Logs werden nicht ins Issue kopiert. Der
Reporter arbeitet nur mit GitHub-APIs und vertrauenswürdigem Code von `main`.
Er ändert keine Branches, Labels, Freigaben oder Merge-Entscheidungen.

Status und Readiness beziehen sich auf genau einen aktuellen CI-Lauf samt
Versuch und HEAD-SHA. Alle erforderlichen Jobs müssen in diesem selben Lauf
erfolgreich sein; grüne Jobs verschiedener Läufe werden nicht kombiniert.
Nach dem Sammeln der Nachweise werden PR und CI nochmals gelesen, damit ein
zwischenzeitlich geänderter Stand nicht als geprüft erscheint.

Der Readiness-Aufruf mit `--allow-open` darf einen vollständig ausgeführten Audit
erfolgreich abschließen, während menschliche Gates noch `OPEN` sind. Der Bericht
bleibt dann `ready: false` und nennt die offenen Nachweise; ein `FAIL` lässt den
Aufruf weiterhin fehlschlagen. Ein grüner Audit-Job ersetzt deshalb weder den
Berichtsinhalt noch Review, Screenshots oder die bewusste Merge-Entscheidung.

Maßgeblich für die automatische Reparatur ist die ausdrücklich gestartete CI
(`workflow_dispatch`) auf der aktuellen PR-SHA. Ein zusätzlicher PR-Lauf kann
wegen GitHub-Regeln `action_required` anzeigen. Das ist weiterhin gesondert in
GitHub zu prüfen; der Statusbericht genehmigt diesen Lauf nicht automatisch.

Vor der Planung werden bis zu fünf passende offene PRs desselben Repositories
mit SHA, Beschreibung, Dateiliste und begrenzten Patches bereitgestellt.
Ausgelassene Dateien/Patches sind gekennzeichnet. Der Plan soll vorhandene Arbeit
als bereits vorhanden / übernehmen / korrigieren / neu erforderlich einordnen.
Das ist Planungskontext, keine Freigabe zum Kopieren oder zum Ändern fremder PRs.

Screenshot-Belege bleiben ein getrennter Schritt: Die bestehende Playwright-CI
lädt `ui-screenshots-and-reports` aus `test-results/` hoch. UI-Tests sollen echte,
anonymisierte Erfolgsansichten dort speichern (`SAVE_UI_SCREENSHOTS=1`). Nach
Sichtprüfung werden ausgewählte Bilder unter `docs/screenshots/` committed und
im PR erklärt. Der textbasierte Modell-Scope erhält keine binären Schreibrechte.
Ein Artefakt allein erfüllt das Gate für committed Screenshots noch nicht.

Die Neuerungen sind erst nach Review/Merge des Infrastruktur-PRs nach `main`
und anschließender Synchronisation mit `dev` aktiv. Laufende ältere Aufträge
werden nicht nachträglich umgeschrieben. Ein echter kompletter KI-Reparaturzyklus
bleibt separat mit Run-URLs und SHAs nachzuweisen.

## Reproducible tests and evidence limits

`tests/ai_pipeline/` exercises different issue numbers and plan versions through
the same authorization, artifact, repair and publisher implementation. Negative
tests cover forged/edited approvals, scope changes, path escapes, symlinks,
oversized content, pending replans, foreign PRs, stale commits and attempts,
newer CI runs on the same SHA, duplicate continuations and repair caps.
Publisher/API tests call the production JavaScript against deterministic API
fixtures, including dispatch recovery and exact-run readiness. Planner tests
cover response validation, bounded retries, fallback and content-free diagnostics.
Contract tests verify permissions, trusted checkouts, triggers and
absence of retired controllers. Release tests inspect real archives and hashes.

The local end-to-end harness creates isolated Git repositories, deliberately
produces a failing test, validates a bounded repair, and runs pytest again to
prove the repaired result. It uses deterministic edits and API fixtures, **not a
live model or a live GitHub publication**. It never damages the application PR.

After infrastructure review and activation on `main`, synchronize `dev`, then
run a fresh owner-approved task and another independently approved issue
without changing controller code. Record actual workflow URLs,
SHA values, generated PRs, full CI and readiness results. A real model repair
cycle is only proven when it actually occurs. Test intentional failures only in
an explicitly authorized disposable test repository; never inject faults into
#108 or a production branch. Keep any unexecuted live stage OPEN in the report.

## Files and release boundary

- `scripts/automation/`: shared authorization, scope, artifact and GitHub logic.
- `scripts/issue_implement.py`, `ci_repair.py`, `ai_merge_readiness.py`: thin generic
  entrypoints; planner/model-router remain reusable and read-only as appropriate.
- `.github/workflows/ai-issue-implement.yml`, `opencode-ci-self-repair.yml`,
  `ai-merge-readiness.yml`: generic orchestration. `ai-automation-tests.yml` replaces
  the three separate issue-specific guard workflows.
- `.opencode/agents/ai-task.md`: deny-by-default template, restricted further by
  the runtime owner scope; no committed per-issue agent.

AI tooling is excluded from release assets created by `scripts/build_release.py`.
Normal build, development and installation helpers are retained. This does not
rewrite already published assets or change GitHub's automatic source archives.
