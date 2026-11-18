'use strict';

// Trusted API-only reporting: no candidate checkout, artifact execution or model text.
const branchPattern = /^ai\/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$/;
const {latestDispatchedRun} = require('./ci_evidence.cjs');

function mayReplace(existing, {ci, run, context, activeController, controllerFailure}) {
  const priorCI = /<!-- ai-status-ci:([0-9]+):(?:([0-9]+):)?([12]) -->/.exec(existing?.body || '');
  if (!priorCI) return true;
  if (!ci || Number(priorCI[1]) > run.id ||
      (Number(priorCI[1]) === run.id && Number(priorCI[2] || 1) > run.run_attempt)) return false;
  if (Number(priorCI[1]) !== run.id || Number(priorCI[2] || 1) !== run.run_attempt) return true;
  const priorController = /<!-- ai-status-controller:([0-9]+) -->/.exec(existing?.body || '');
  if (activeController && priorController && context.runId < Number(priorController[1])) return false;
  const explicitResume = activeController && priorController && context.runId > Number(priorController[1]);
  return priorCI[3] !== '2' || controllerFailure || Boolean(explicitResume);
}

async function continuationFailureSource({github, context, recovery}) {
  const {sourceIdentity, validateRun} = require('./continuation.cjs');
  const identity = sourceIdentity(context);
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const repository = `${repo.owner}/${repo.repo}`;
  const {data: original} = await github.rest.actions.getWorkflowRun({...repo, run_id: identity.id});
  validateRun(original, identity, repository);
  const prs = await github.paginate(github.rest.pulls.list,
    {...repo, state: 'open', head: `${repo.owner}:${original.head_branch}`, per_page: 100});
  const matching = prs.filter(pr => pr.state === 'open' && pr.user?.login === 'github-actions[bot]' &&
    pr.base.ref === 'dev' && pr.head.ref === original.head_branch &&
    pr.head.repo?.full_name === repository);
  if (matching.length !== 1) return null;
  const pr = matching[0];
  const latest = await latestDispatchedRun({github, repo, branch: pr.head.ref, headSha: pr.head.sha});
  if (recovery) {
    const id = Number(recovery.ci_run_id), attempt = Number(recovery.ci_run_attempt);
    if (!/^[1-9][0-9]*$/.test(String(recovery.ci_run_id)) || !Number.isSafeInteger(id) ||
        !/^[1-9][0-9]*$/.test(String(recovery.ci_run_attempt)) || !Number.isSafeInteger(attempt) ||
        !/^[0-9a-f]{40}$/.test(recovery.ci_head_sha || '')) return null;
    const {data: recovered} = await github.rest.actions.getWorkflowRun({...repo, run_id:id});
    validateRun(recovered, {id, attempt, sha:recovery.ci_head_sha, branch:original.head_branch}, repository);
    if (pr.head.sha !== recovered.head_sha || latest?.id !== id || latest.run_attempt !== attempt) return null;
    return {run:recovered, pr};
  }
  // A newer CI must report its own outcome. Do not overwrite it with an older
  // controller failure. A moved branch without CI still needs a visible stop.
  if (latest && (latest.id !== original.id || latest.run_attempt !== original.run_attempt)) return null;
  return {run: original, pr, moved: pr.head.sha !== original.head_sha};
}

async function report({github, context, phase, source, recovery, controller = false}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const repository = `${repo.owner}/${repo.repo}`;
  let number, commandId, run, pr, moved = false;
  const continuation = context.eventName === 'workflow_dispatch' && context.payload.inputs?.ci_run_id;
  const controllerFailure = phase === 'repair-failure' || phase === 'continuation-failure';
  const activeController = controller || Boolean(continuation) || controllerFailure;
  if (controllerFailure && recovery) {
    source = await continuationFailureSource({github, context, recovery});
    if (!source) return;
  }
  if (continuation && !source) {
    const {resolveSource} = require('./continuation.cjs');
    source = await resolveSource({github, context});
  }
  if (controllerFailure && !source && (continuation || context.eventName === 'workflow_run')) {
    source = await continuationFailureSource({github, context});
    if (!source) return;
  }
  const ci = context.eventName === 'workflow_run' || Boolean(source);
  if (ci) {
    const expected = source?.run || context.payload.workflow_run;
    const match = branchPattern.exec(expected?.head_branch || '');
    if (!match || expected.head_repository?.full_name !== repository) return;
    ({data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: expected.id}));
    if (run.path !== '.github/workflows/ci.yml' || run.event !== 'workflow_dispatch' ||
        run.head_sha !== expected.head_sha || run.run_attempt !== expected.run_attempt ||
        run.head_repository?.full_name !== repository) return;
    const latest = await latestDispatchedRun({github, repo, branch: run.head_branch, headSha: run.head_sha});
    if (!source?.moved && (!latest || latest.id !== run.id || latest.run_attempt !== run.run_attempt)) return;
    const prs = await github.paginate(github.rest.pulls.list,
      {...repo, state: 'open', head: `${repo.owner}:${run.head_branch}`, per_page: 100});
    const matches = prs.filter(p => p.head.ref === run.head_branch && p.base.ref === 'dev' &&
      (p.head.sha === run.head_sha || (controllerFailure && source?.moved)) &&
      p.head.repo?.full_name === repository &&
      p.user?.login === 'github-actions[bot]');
    if (matches.length !== 1) return;
    pr = matches[0];
    moved = pr.head.sha !== run.head_sha;
    number = Number(match[1]);
    commandId = Number(/<!-- ai-implementation-command: ([1-9][0-9]*) -->/.exec(pr.body || '')?.[1]);
  } else if (context.eventName === 'issue_comment' || context.eventName === 'issues') {
    if (context.actor.toLowerCase() !== repo.owner.toLowerCase() || context.payload.issue?.pull_request) return;
    number = context.payload.issue?.number;
    commandId = context.payload.comment?.id || context.runId;
    ({data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: context.runId}));
    if (phase !== 'failure') {
      const prs = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
      pr = prs.find(p => p.user?.login === 'github-actions[bot]' && p.base.ref === 'dev' &&
        p.head.repo?.full_name === repository && branchPattern.test(p.head.ref) &&
        p.body?.includes(`<!-- ai-implementation-command: ${commandId} -->`));
    }
  } else return;
  if (!Number.isSafeInteger(number) || number < 1 || !Number.isSafeInteger(commandId) || commandId < 1) return;
  const {data: issue} = await github.rest.issues.get({...repo, issue_number: number});
  if (issue.state !== 'open' || issue.pull_request) return;
  const comments = await github.paginate(github.rest.issues.listComments,
    {...repo, issue_number: number, per_page: 100});
  if (comments.length > 2000) throw new Error('Status history limit exceeded');
  if (ci && !comments.some(c => c.id === commandId &&
      c.user?.login?.toLowerCase() === repo.owner.toLowerCase())) return;
  const repairFailure = phase === 'repair-failure';
  const diagnosticRun = controllerFailure ? context.runId : run.id;
  const {data: jobs} = await github.rest.actions.listJobsForWorkflowRun({...repo, run_id: diagnosticRun, per_page: 100});
  const failed = jobs.jobs.flatMap(j => j.steps || []).filter(s => s.conclusion === 'failure');
  const jobsFailed = jobs.jobs.some(j => j.conclusion === 'failure');
  const failedState = run.conclusion === 'failure' || jobsFailed || phase?.endsWith('failure');
  const title = phase === 'started' ? 'Umsetzung läuft' :
    phase === 'continuation-failure' ? 'KI-Fortsetzung angehalten' : repairFailure ? 'KI-Reparatur angehalten' : ci ? (run.status !== 'completed' ? 'CI läuft' :
    run.conclusion === 'success' ? 'CI bestanden – Review erforderlich' : 'CI benötigt Aufmerksamkeit') :
    failedState ? 'Workflow angehalten' : 'Draft-PR veröffentlicht – CI gestartet';
  const marker = `<!-- ai-workflow-status:${commandId} -->`;
  let existing = comments.find(c => c.user?.login === 'github-actions[bot]' && c.body?.startsWith(marker));
  if (phase === 'started' && existing) return;
  const replacement = {ci, run, context, activeController, controllerFailure};
  if (!mayReplace(existing, replacement)) return;
  const url = `https://github.com/${repository}/actions/runs/${diagnosticRun}`;
  const ciMarker = ci ? `\n<!-- ai-status-ci:${run.id}:${run.run_attempt}:${controllerFailure ? 2 : 1} -->` : '';
  let body = `### KI-Workflow: ${title}\n\n[Lauf öffnen](${url})`;
  if (pr) body += ` · [Draft-PR #${pr.number}](https://github.com/${repository}/pull/${pr.number})\n\nStand: \`${pr.head.sha}\`.`;
  if (ci) {
    const commits = await github.paginate(github.rest.pulls.listCommits,
      {...repo, pull_number: pr.number, per_page: 100});
    const attempts = commits.filter(c => /^fix\(ai-ci\): .* attempt [12](?:\n|$)/.test(c.commit.message)).length;
    body += `\n\nKI-Reparaturen: **${attempts}/2**. Geprüfter CI-Lauf: **${run.id}, Versuch ${run.run_attempt}** ` +
      `(workflow_dispatch), SHA \`${run.head_sha}\`. Ein zusätzlicher PR-Lauf kann eine GitHub-Freigabe verlangen.`;
    if (moved) body += '\n\nDer PR hat inzwischen einen anderen Commit. Für diesen Stand ist hier kein neuer CI-Lauf belegt.';
    const {data: artifacts} = await github.rest.actions.listWorkflowRunArtifacts({...repo, run_id: run.id, per_page: 100});
    const ui = artifacts.artifacts.find(a => a.name === 'ui-screenshots-and-reports' && !a.expired);
    if (ui) body += `\n\n[UI-Screenshots und Berichte](https://github.com/${repository}/actions/runs/${run.id}/artifacts/${ui.id}) ` +
      'zur Sichtprüfung. Das Artefakt ersetzt keine geprüften, committed Screenshots.';
    body += `\n\n[Software-Prüfberichte](https://github.com/${repository}/actions/workflows/ai-merge-readiness.yml) ` +
      'auf die aktuelle PR-SHA prüfen.';
    body += controllerFailure ? '\n\nNächster Schritt: Den fehlgeschlagenen Controller-Schritt und die dort genannten Laufdaten prüfen. ' +
      'Eine begonnene CI über die Fortsetzung mit ihrer Run-ID wieder aufnehmen; nicht erneut implementieren. ' +
      'Eine erfolgreiche Reparatur ist nicht belegt.' :
      run.status !== 'completed' ? '\n\nNächster Schritt: CI-Ergebnis abwarten.' :
      run.conclusion === 'success' ? '\n\nNächster Schritt: Prüfbericht, Screenshots und Review prüfen; danach bewusst mergen.' :
      attempts >= 2 ? '\n\nReparaturlimit erreicht. Nächster Schritt: Fehler menschlich prüfen.' :
      '\n\nEine begrenzte KI-Reparatur kann folgen, wenn Draft, Freigabe und Dateiumfang weiterhin gültig sind. ' +
      'Ein fehlgeschlagener CI-Lauf allein bestätigt noch keinen erfolgreichen Reparaturstart.';
  } else if (phase === 'started') {
    body += '\n\nDer Startauftrag wird geprüft; danach folgen Modelllauf, Formatierung und unabhängige Veröffentlichung. ' +
      'Nächster Schritt: Ergebnis abwarten. Der Bot ergänzt PR und CI nach erfolgreicher Veröffentlichung.';
  } else if (phase === 'planning-failure') {
    body += '\n\nDie Planung wurde nicht erfolgreich veröffentlicht. Nächster Schritt: Das Artefakt `ai-planner-diagnostics` ' +
      'und die konkrete Fehlerklasse im Lauf prüfen. Die begrenzten Modellversuche sind bereits beendet. ' +
      'Nach Behebung bei vorhandenem Plan mit `/ai answer Bitte erneut planen` einen neuen Kommentar posten; ' +
      'ohne bisherigen Plan das Label `ai:plan` entfernen und erneut setzen. Keine Freigabe für einen fehlenden Plan erteilen.';
  } else if (failedState) {
    body += '\n\nNächster Schritt: Den fehlgeschlagenen Schritt im Lauf prüfen. ' +
      'Bei fehlendem Dateiumfang: Für neue Pläne nach der Bot-Freigabe `/ai start vN` posten. ' +
      'Für ältere Pläne `/ai implement vN` **zusammen mit dem vollständigen JSON-Dateiumfang** als neuen Kommentar posten. ' +
      'Bearbeiten eines alten Kommentars startet keinen Lauf. `approve` bestätigt den Plan; `start` startet die Umsetzung.';
  } else {
    body += '\n\nNächster Schritt: CI und Prüfbericht abwarten. Die Veröffentlichung ist noch keine Merge-Freigabe.';
  }
  if (failed.length) body += '\n\nFehlgeschlagene Schritte: ' + failed.map(s => `\`${s.name.replace(/[`\r\n]/g, '')}\``).join(', ');
  if (ci) {
    const {data: current} = await github.rest.pulls.get({...repo, pull_number:pr.number});
    const latest = await latestDispatchedRun({github, repo, branch:pr.head.ref, headSha:pr.head.sha});
    if (current.state !== 'open' || current.head.sha !== pr.head.sha ||
        current.head.ref !== pr.head.ref || current.head.repo?.full_name !== repository ||
        current.base.ref !== 'dev' || (moved ? latest !== null :
          !latest || latest.id !== run.id || latest.run_attempt !== run.run_attempt ||
          latest.status !== run.status || latest.conclusion !== run.conclusion)) return;
    const currentComments = await github.paginate(github.rest.issues.listComments,
      {...repo, issue_number:number, per_page:100});
    if (currentComments.length > 2000) throw new Error('Status history limit exceeded');
    existing = currentComments.find(c => c.user?.login === 'github-actions[bot]' && c.body?.startsWith(marker));
    if (!mayReplace(existing, replacement)) return;
  }
  // Passive CI observers must not become a newer repair controller merely
  // because GitHub assigned their reporting workflow a larger run ID. Preserve
  // the lineage from the final comment read, not the earlier evidence snapshot.
  const priorController = /<!-- ai-status-controller:([0-9]+) -->/.exec(existing?.body || '');
  const controllerId = activeController ? context.runId : priorController?.[1];
  const controllerMarker = ci && controllerId ? `\n<!-- ai-status-controller:${controllerId} -->` : '';
  body = `${marker}${ciMarker}${controllerMarker}\n${body}`;
  if (existing) {
    if (existing.body === body) return;
    await github.rest.issues.updateComment({...repo, comment_id: existing.id, body});
  } else await github.rest.issues.createComment({...repo, issue_number: number, body});
}

module.exports = {report};
