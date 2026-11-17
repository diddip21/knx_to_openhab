'use strict';

// Trusted API-only reporting: no candidate checkout, artifact execution or model text.
const branchPattern = /^ai\/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$/;

async function report({github, context, phase}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const repository = `${repo.owner}/${repo.repo}`;
  let number, commandId, run, pr;
  if (context.eventName === 'workflow_run') {
    const expected = context.payload.workflow_run;
    const match = branchPattern.exec(expected?.head_branch || '');
    if (!match || expected.head_repository?.full_name !== repository) return;
    ({data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: expected.id}));
    if (run.path !== '.github/workflows/ci.yml' || run.event !== 'workflow_dispatch' ||
        run.head_sha !== expected.head_sha || run.head_repository?.full_name !== repository) return;
    const prs = await github.paginate(github.rest.pulls.list,
      {...repo, state: 'open', head: `${repo.owner}:${run.head_branch}`, per_page: 100});
    const matches = prs.filter(p => p.head.ref === run.head_branch && p.base.ref === 'dev' &&
      p.head.sha === run.head_sha && p.head.repo?.full_name === repository &&
      p.user?.login === 'github-actions[bot]');
    if (matches.length !== 1) return;
    pr = matches[0];
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
  if (context.eventName === 'workflow_run' && !comments.some(c => c.id === commandId &&
      c.user?.login?.toLowerCase() === repo.owner.toLowerCase())) return;
  const repairFailure = phase === 'repair-failure';
  const diagnosticRun = repairFailure ? context.runId : run.id;
  const {data: jobs} = await github.rest.actions.listJobsForWorkflowRun({...repo, run_id: diagnosticRun, per_page: 100});
  const failed = jobs.jobs.flatMap(j => j.steps || []).filter(s => s.conclusion === 'failure');
  const jobsFailed = jobs.jobs.some(j => j.conclusion === 'failure');
  const failedState = run.conclusion === 'failure' || jobsFailed || phase?.endsWith('failure');
  const ci = context.eventName === 'workflow_run';
  const title = phase === 'started' ? 'Umsetzung läuft' : repairFailure ? 'KI-Reparatur angehalten' : ci ? (run.status !== 'completed' ? 'CI läuft' :
    run.conclusion === 'success' ? 'CI bestanden – Review erforderlich' : 'CI benötigt Aufmerksamkeit') :
    failedState ? 'Workflow angehalten' : 'Draft-PR veröffentlicht – CI gestartet';
  const marker = `<!-- ai-workflow-status:${commandId} -->`;
  const existing = comments.find(c => c.user?.login === 'github-actions[bot]' && c.body?.startsWith(marker));
  if (phase === 'started' && existing) return;
  const priorCI = /<!-- ai-status-ci:([0-9]+):([12]) -->/.exec(existing?.body || '');
  if (priorCI && (!ci || Number(priorCI[1]) > run.id ||
      (Number(priorCI[1]) === run.id && priorCI[2] === '2' && !repairFailure))) return;
  const url = `https://github.com/${repository}/actions/runs/${diagnosticRun}`;
  const ciMarker = ci ? `\n<!-- ai-status-ci:${run.id}:${repairFailure ? 2 : 1} -->` : '';
  let body = `${marker}${ciMarker}\n### KI-Workflow: ${title}\n\n[Lauf öffnen](${url})`;
  if (pr) body += ` · [Draft-PR #${pr.number}](https://github.com/${repository}/pull/${pr.number})\n\nStand: \`${pr.head.sha}\`.`;
  if (ci) {
    const commits = await github.paginate(github.rest.pulls.listCommits,
      {...repo, pull_number: pr.number, per_page: 100});
    const attempts = commits.filter(c => /^fix\(ai-ci\): .* attempt [12](?:\n|$)/.test(c.commit.message)).length;
    body += `\n\nKI-Reparaturen: **${attempts}/2**. Maßgeblich ist die ausdrücklich gestartete CI ` +
      '(workflow_dispatch) auf dieser SHA. Ein zusätzlicher PR-Lauf kann eine GitHub-Freigabe verlangen.';
    const {data: artifacts} = await github.rest.actions.listWorkflowRunArtifacts({...repo, run_id: run.id, per_page: 100});
    const ui = artifacts.artifacts.find(a => a.name === 'ui-screenshots-and-reports' && !a.expired);
    if (ui) body += `\n\n[UI-Screenshots und Berichte](https://github.com/${repository}/actions/runs/${run.id}/artifacts/${ui.id}) ` +
      'zur Sichtprüfung. Das Artefakt ersetzt keine geprüften, committed Screenshots.';
    body += `\n\n[Software-Prüfberichte](https://github.com/${repository}/actions/workflows/ai-merge-readiness.yml) ` +
      'auf die aktuelle PR-SHA prüfen.';
    body += repairFailure ? '\n\nNächster Schritt: Den Reparaturlauf menschlich prüfen. Eine erfolgreiche Reparatur ist nicht belegt.' :
      run.status !== 'completed' ? '\n\nNächster Schritt: CI-Ergebnis abwarten.' :
      run.conclusion === 'success' ? '\n\nNächster Schritt: Prüfbericht, Screenshots und Review prüfen; danach bewusst mergen.' :
      attempts >= 2 ? '\n\nReparaturlimit erreicht. Nächster Schritt: Fehler menschlich prüfen.' :
      '\n\nEine begrenzte KI-Reparatur kann folgen, wenn Draft, Freigabe und Dateiumfang weiterhin gültig sind. ' +
      'Ein fehlgeschlagener CI-Lauf allein bestätigt noch keinen erfolgreichen Reparaturstart.';
  } else if (phase === 'started') {
    body += '\n\nDer Startauftrag wird geprüft; danach folgen Modelllauf, Formatierung und unabhängige Veröffentlichung. ' +
      'Nächster Schritt: Ergebnis abwarten. Der Bot ergänzt PR und CI nach erfolgreicher Veröffentlichung.';
  } else if (phase === 'planning-failure') {
    body += '\n\nDie Planung wurde nicht erfolgreich veröffentlicht. Nächster Schritt: Den Lauf prüfen. ' +
      'Bei vorhandenem Plan mit `/ai answer Bitte erneut planen` einen neuen Kommentar posten; ' +
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
  if (existing) {
    if (existing.body === body) return;
    await github.rest.issues.updateComment({...repo, comment_id: existing.id, body});
  } else await github.rest.issues.createComment({...repo, issue_number: number, body});
}

module.exports = {report};
