'use strict';

// This controller is loaded only from the trusted default branch. A dispatch
// selects a run to inspect; it never authorizes a repair or supplies source code.
const branchPattern = /^ai\/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$/;
const shaPattern = /^[0-9a-f]{40}$/;
const {latestDispatchedRun} = require('./ci_evidence.cjs');
const sleepDefault = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const repoArgs = context => ({owner: context.repo.owner, repo: context.repo.repo});

function positiveInteger(value, name) {
  if (!/^[1-9][0-9]*$/.test(String(value)) || !Number.isSafeInteger(Number(value))) {
    throw new Error(`Invalid ${name}`);
  }
  return Number(value);
}

function sourceIdentity(context) {
  if (context.eventName === 'workflow_run') {
    const run = context.payload.workflow_run;
    if (context.payload.action !== 'completed' || !run || !branchPattern.test(run.head_branch || '')) {
      throw new Error('Not a completed AI CI workflow event');
    }
    const identity = {id: positiveInteger(run.id, 'CI run ID'),
      attempt: positiveInteger(run.run_attempt, 'CI run attempt'), sha: run.head_sha,
      branch: run.head_branch};
    if (!shaPattern.test(identity.sha || '')) throw new Error('Invalid CI head SHA');
    return identity;
  }
  if (context.eventName !== 'workflow_dispatch') throw new Error('Unsupported CI continuation event');
  const owner = context.repo.owner.toLowerCase();
  const actor = String(context.actor || '').toLowerCase();
  const defaultBranch = context.payload.repository?.default_branch;
  if (![owner, 'github-actions[bot]'].includes(actor) || !defaultBranch ||
      context.ref !== `refs/heads/${defaultBranch}`) {
    throw new Error('CI continuation must be dispatched by the owner or bot on the default branch');
  }
  const inputs = context.payload.inputs || {};
  const identity = {id: positiveInteger(inputs.ci_run_id, 'CI run ID'),
    attempt: positiveInteger(inputs.ci_run_attempt, 'CI run attempt'), sha: inputs.ci_head_sha};
  if (!shaPattern.test(identity.sha || '')) throw new Error('Invalid CI head SHA');
  return identity;
}

function validateRun(run, identity, repository) {
  if (!run || run.id !== identity.id || run.run_attempt !== identity.attempt ||
      run.head_sha !== identity.sha || (identity.branch && run.head_branch !== identity.branch) ||
      run.name !== 'CI' || run.path !== '.github/workflows/ci.yml' ||
      run.event !== 'workflow_dispatch' || run.head_repository?.full_name !== repository ||
      !branchPattern.test(run.head_branch || '')) {
    throw new Error('CI run identity, attempt, repository, workflow or SHA does not match');
  }
  return run;
}

async function resolveSource({github, context, waitForCompletion = false,
  sleep = sleepDefault, maxPolls = 150, pollMilliseconds = 10000}) {
  const repo = repoArgs(context);
  const identity = sourceIdentity(context);
  const repository = `${repo.owner}/${repo.repo}`;
  let run;
  for (let poll = 0; poll <= maxPolls; poll++) {
    ({data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: identity.id}));
    validateRun(run, identity, repository);
    if (!waitForCompletion || run.status === 'completed') break;
    if (poll === maxPolls) throw new Error('Timed out waiting for the explicitly dispatched CI run');
    await sleep(pollMilliseconds);
  }
  const latest = await latestDispatchedRun({github, repo, branch: run.head_branch, headSha: run.head_sha});
  if (!latest || latest.id !== run.id || latest.run_attempt !== run.run_attempt) return null;
  const open = await github.paginate(github.rest.pulls.list,
    {...repo, state: 'open', head: `${repo.owner}:${run.head_branch}`, per_page: 100});
  const matches = open.filter(pr => pr.state === 'open' && pr.user?.login === 'github-actions[bot]' &&
    pr.base.ref === 'dev' && pr.head.ref === run.head_branch && pr.head.sha === run.head_sha &&
    pr.head.repo?.full_name === repository);
  if (matches.length > 1) throw new Error('More than one current AI PR matches the CI run');
  // A duplicate continuation after a published repair is stale. It is a no-op,
  // rather than another repair of an already superseded commit.
  return matches.length === 1 ? {run, pr: matches[0]} : null;
}

async function routeContinuation({github, context, core, sleep = sleepDefault}) {
  core.setOutput('eligible', 'false');
  core.setOutput('repair', 'false');
  const source = await resolveSource({github, context, waitForCompletion: true, sleep});
  if (!source) {
    core.info('CI continuation is superseded or has no matching current open AI PR; no action taken');
    return null;
  }
  const {run, pr} = source;
  const outputs = {eligible: 'true', repair: String(run.conclusion === 'failure' && pr.draft === true),
    ci_run_id: String(run.id), ci_run_attempt: String(run.run_attempt), head_sha: run.head_sha,
    head_branch: run.head_branch, conclusion: run.conclusion, pr_number: String(pr.number)};
  for (const [key, value] of Object.entries(outputs)) core.setOutput(key, value);
  await github.rest.actions.createWorkflowDispatch({...repoArgs(context),
    workflow_id: 'ai-merge-readiness.yml', ref: context.payload.repository.default_branch,
    inputs: {pr_number: String(pr.number)}});
  return source;
}

async function dispatchCiAndContinuation({github, context, core, branch, headSha,
  sleep = sleepDefault}) {
  if (!branchPattern.test(branch || '') || !shaPattern.test(headSha || '')) {
    throw new Error('Invalid AI branch or commit for CI dispatch');
  }
  const repo = repoArgs(context);
  const defaultBranch = context.payload.repository?.default_branch;
  if (!defaultBranch) throw new Error('Default branch is required for trusted continuation');
  // GitHub returns the ID of this exact dispatch. Do not guess the newest run
  // for a branch, and never retry the dispatch after an ambiguous response.
  const response = await github.rest.actions.createWorkflowDispatch({...repo,
    workflow_id: 'ci.yml', ref: branch,
    headers: {'X-GitHub-Api-Version': '2026-03-10'}});
  const runId = positiveInteger(response?.data?.workflow_run_id, 'dispatched CI run ID');
  core?.setOutput?.('ci_run_id', String(runId));
  core?.info(`Dispatched CI https://github.com/${repo.owner}/${repo.repo}/actions/runs/${runId} ` +
    `for expected commit ${headSha}`);
  let run;
  for (let poll = 0; poll < 10; poll++) {
    try {
      ({data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: runId}));
      break;
    } catch (error) {
      if (error.status !== 404 || poll === 9) {
        throw new Error(`CI ${runId} was dispatched, but its source could not be verified. ` +
          'Inspect that exact run before resuming; no additional CI was started.', {cause: error});
      }
      await sleep(2000);
    }
  }
  validateRun(run, {id: runId, attempt: 1, sha: headSha, branch}, `${repo.owner}/${repo.repo}`);
  core?.info(`CI run ${run.id} started for ${headSha}; dispatching trusted continuation`);
  const inputs = {ci_run_id: String(run.id), ci_run_attempt: String(run.run_attempt),
    ci_head_sha: run.head_sha};
  for (const [key, value] of Object.entries(inputs)) core?.setOutput?.(key, value);
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const continuation = await github.rest.actions.createWorkflowDispatch({...repo,
        workflow_id: 'opencode-ci-self-repair.yml', ref: defaultBranch, inputs,
        headers: {'X-GitHub-Api-Version': '2026-03-10'}});
      const continuationId = continuation?.data?.workflow_run_id;
      if (Number.isSafeInteger(continuationId) && continuationId > 0) {
        core?.setOutput?.('continuation_run_id', String(continuationId));
        core?.info(`Trusted CI continuation: https://github.com/${repo.owner}/${repo.repo}/actions/runs/${continuationId}`);
      }
      return run;
    } catch (error) {
      const retryable = !error.status || error.status === 429 || error.status >= 500;
      if (!retryable || attempt === 2) {
        throw new Error(`CI ${run.id} was started, but continuation dispatch failed. ` +
          `Resume opencode-ci-self-repair.yml on ${defaultBranch} with ${JSON.stringify(inputs)}. ` +
          'Do not restart implementation or CI to resume this completed publication.', {cause: error});
      }
      // Repeating only the continuation is safe: duplicate source identities are
      // serialized, and current-PR-SHA validation makes superseded runs no-ops.
      await sleep(2000 * (attempt + 1));
    }
  }
  return run;
}

module.exports = {dispatchCiAndContinuation, resolveSource, routeContinuation, sourceIdentity, validateRun};
