'use strict';

// Stateful API fixtures exercise the real controller, never live GitHub writes.
const test = require('node:test');
const assert = require('node:assert/strict');
const {dispatchCiAndContinuation, resolveSource, routeContinuation, sourceIdentity} =
  require('../../scripts/automation/continuation.cjs');

const BASE = 'a'.repeat(40);
const FIX_ONE = 'b'.repeat(40);
const FIX_TWO = 'c'.repeat(40);
const branch = 'ai/issue-1234-plan-v5-run-1000';
const repository = 'owner/repo';

function apiFixture() {
  const pr = {number: 50, state: 'open', draft: true,
    user: {login: 'github-actions[bot]'}, base: {ref: 'dev'},
    head: {ref: branch, sha: BASE, repo: {full_name: repository}}};
  const initial = {id: 6000, run_attempt: 1, name: 'CI', path: '.github/workflows/ci.yml',
    event: 'workflow_dispatch', status: 'completed', conclusion: 'failure',
    head_branch: branch, head_sha: BASE, head_repository: {full_name: repository},
    created_at: '2026-01-01T12:00:00Z'};
  const state = {runs: new Map([[initial.id, initial]]), open: [pr], pr,
    requests: [], reads: [], pauses: [], outputs: {}, nextId: 6001};
  const context = {eventName: 'workflow_dispatch', actor: 'github-actions[bot]',
    ref: 'refs/heads/main', repo: {owner: 'owner', repo: 'repo'},
    payload: {repository: {default_branch: 'main'}, inputs: {
      ci_run_id: '6000', ci_run_attempt: '1', ci_head_sha: BASE}}};
  const github = {rest: {
    actions: {
      createWorkflowDispatch: async args => {
        state.requests.push(structuredClone(args));
        if (args.workflow_id !== 'ci.yml') return {status: 204, data: ''};
        const run = {...initial, id: state.nextId++, head_branch: args.ref,
          head_sha: state.pr.head.sha, status: 'queued', conclusion: null};
        state.runs.set(run.id, run);
        return {status: 200, data: {workflow_run_id: run.id,
          html_url: `https://github.com/${repository}/actions/runs/${run.id}`}};
      },
      getWorkflowRun: async ({run_id}) => {
        state.reads.push(run_id);
        const run = state.runs.get(run_id);
        if (!run) throw Object.assign(new Error('Unknown run'), {status: 404});
        return {data: structuredClone(run)};
      },
      listWorkflowRuns: async args => ({data: {workflow_runs: [...state.runs.values()]
        .filter(run => (!args.event || run.event === args.event) &&
          (!args.branch || run.head_branch === args.branch) &&
          (!args.head_sha || run.head_sha === args.head_sha))
        .sort((a, b) => b.id - a.id).map(run => structuredClone(run))}})
    },
    pulls: {list: async () => ({data: structuredClone(state.open)})}
  }, paginate: async (method, args) => {
    const {data} = await method(args);
    return Array.isArray(data) ? data : data.workflow_runs;
  }};
  const core = {info() {}, setOutput: (name, value) => {state.outputs[name] = value;}};
  const sleep = async duration => {state.pauses.push(duration);};
  return {github, context, core, state, sleep, branch, headSha: BASE};
}

function selectedContext(f, run) {
  return {...f.context, payload: {...f.context.payload, inputs: {
    ci_run_id: String(run.id), ci_run_attempt: String(run.run_attempt),
    ci_head_sha: run.head_sha}}};
}

test('publication dispatches CI and its trusted continuation using the returned run ID', async () => {
  const f = apiFixture();
  const run = await dispatchCiAndContinuation(f);
  assert.equal(run.id, 6001);
  assert.equal(f.state.requests.length, 2);
  assert.equal(f.state.requests[0].workflow_id, 'ci.yml');
  assert.equal(f.state.requests[0].ref, branch);
  assert.equal(f.state.requests[0].headers['X-GitHub-Api-Version'], '2026-03-10');
  assert.deepEqual(f.state.requests[1], {owner: 'owner', repo: 'repo',
    workflow_id: 'opencode-ci-self-repair.yml', ref: 'main',
    inputs: {ci_run_id: '6001', ci_run_attempt: '1', ci_head_sha: BASE},
    headers: {'X-GitHub-Api-Version': '2026-03-10'}});
  assert.deepEqual(f.state.outputs, {ci_run_id: '6001', ci_run_attempt: '1', ci_head_sha: BASE});
});

test('an ambiguous CI dispatch never starts another CI run or guesses an unrelated run', async () => {
  for (const response of [{status: 204, data: ''}, {status: 200, data: {}},
    {status: 200, data: {workflow_run_id: 'not-an-id'}}]) {
    const f = apiFixture();
    f.github.rest.actions.createWorkflowDispatch = async args => {
      f.state.requests.push(args);
      return response;
    };
    await assert.rejects(() => dispatchCiAndContinuation(f), /CI run ID/);
    assert.equal(f.state.requests.length, 1);
    assert.equal(f.state.reads.length, 0);
  }
  const f = apiFixture();
  f.github.rest.actions.createWorkflowDispatch = async args => {
    f.state.requests.push(args);
    throw Object.assign(new Error('Connection lost after acceptance'), {status: 503});
  };
  await assert.rejects(() => dispatchCiAndContinuation(f), /Connection lost/);
  assert.equal(f.state.requests.length, 1);
});

test('temporary visibility delay retries only the returned run lookup', async () => {
  const f = apiFixture();
  const getRun = f.github.rest.actions.getWorkflowRun;
  let remaining = 2;
  f.github.rest.actions.getWorkflowRun = async args => {
    if (remaining-- > 0) throw Object.assign(new Error('Not visible yet'), {status: 404});
    return getRun(args);
  };
  await dispatchCiAndContinuation(f);
  assert.equal(f.state.requests.filter(args => args.workflow_id === 'ci.yml').length, 1);
  assert.equal(f.state.requests.length, 2);
  assert.equal(f.state.pauses.length, 2);
});

test('failed source lookup preserves the already accepted CI run ID for recovery', async () => {
  const f = apiFixture();
  f.github.rest.actions.getWorkflowRun = async () => {
    throw Object.assign(new Error('Forbidden'), {status: 403});
  };
  await assert.rejects(() => dispatchCiAndContinuation(f), /CI 6001 was dispatched/);
  assert.equal(f.state.outputs.ci_run_id, '6001');
  assert.equal(f.state.requests.length, 1);
});

test('the returned continuation run ID is available without guessing the latest workflow run', async () => {
  const f = apiFixture();
  const dispatch = f.github.rest.actions.createWorkflowDispatch;
  f.github.rest.actions.createWorkflowDispatch = async args => {
    const response = await dispatch(args);
    return args.workflow_id === 'ci.yml' ? response : {status: 200, data: {workflow_run_id: 7001}};
  };
  await dispatchCiAndContinuation(f);
  assert.equal(f.state.outputs.ci_run_id, '6001');
  assert.equal(f.state.outputs.continuation_run_id, '7001');
  assert.equal(f.state.requests.length, 2);
});

test('continuation dispatch retries never republish code or start another CI', async () => {
  const f = apiFixture();
  const dispatch = f.github.rest.actions.createWorkflowDispatch;
  let failures = 2;
  f.github.rest.actions.createWorkflowDispatch = async args => {
    if (args.workflow_id !== 'ci.yml' && failures-- > 0) {
      f.state.requests.push(structuredClone(args));
      throw Object.assign(new Error('Service unavailable'), {status: 503});
    }
    return dispatch(args);
  };
  await dispatchCiAndContinuation(f);
  assert.equal(f.state.requests.filter(args => args.workflow_id === 'ci.yml').length, 1);
  const continuation = f.state.requests.filter(args => args.workflow_id !== 'ci.yml');
  assert.equal(continuation.length, 3);
  assert.deepEqual(continuation[0], continuation[1]);
  assert.deepEqual(continuation[1], continuation[2]);
});

test('permanent continuation failure reports the exact recovery identity', async () => {
  const f = apiFixture();
  const dispatch = f.github.rest.actions.createWorkflowDispatch;
  f.github.rest.actions.createWorkflowDispatch = async args => {
    if (args.workflow_id !== 'ci.yml') {
      f.state.requests.push(args);
      throw Object.assign(new Error('Forbidden'), {status: 403});
    }
    return dispatch(args);
  };
  await assert.rejects(() => dispatchCiAndContinuation(f), error => {
    assert.match(error.message, /CI 6001 was started/);
    assert.match(error.message, /"ci_run_id":"6001"/);
    assert.match(error.message, new RegExp(BASE));
    assert.match(error.message, /Do not restart implementation or CI/);
    return true;
  });
  assert.equal(f.state.requests.length, 2);
});

test('waiting resolves one exact CI attempt and only current PR evidence', async () => {
  const f = apiFixture();
  const run = f.state.runs.get(6000);
  run.status = 'queued';
  run.conclusion = null;
  let ticks = 0;
  const source = await resolveSource({...f, waitForCompletion: true, maxPolls: 2,
    sleep: async () => {
      ticks++;
      run.status = ticks === 1 ? 'in_progress' : 'completed';
      run.conclusion = ticks === 2 ? 'failure' : null;
    }});
  assert.equal(source.run.id, 6000);
  assert.equal(source.pr.number, 50);
  assert.equal(source.run.conclusion, 'failure');
  assert.equal(ticks, 2);
  assert.equal(f.state.requests.length, 0);
});

test('polling is bounded when CI never completes', async () => {
  const f = apiFixture();
  f.state.runs.get(6000).status = 'in_progress';
  await assert.rejects(() => resolveSource({...f, waitForCompletion: true, maxPolls: 2}),
    /Timed out waiting/);
  assert.equal(f.state.pauses.length, 2);
  assert.equal(f.state.requests.length, 0);
});

for (const invalid of ['owner', 'ref', 'run-id', 'attempt', 'sha']) {
  test(`a manual continuation rejects invalid ${invalid} before querying runs`, async () => {
    const f = apiFixture();
    if (invalid === 'owner') f.context.actor = 'unrelated-user';
    if (invalid === 'ref') f.context.ref = `refs/heads/${branch}`;
    if (invalid === 'run-id') f.context.payload.inputs.ci_run_id = '0';
    if (invalid === 'attempt') f.context.payload.inputs.ci_run_attempt = '1.5';
    if (invalid === 'sha') f.context.payload.inputs.ci_head_sha = 'main';
    await assert.rejects(() => resolveSource(f));
    assert.equal(f.state.reads.length, 0);
  });
}

for (const invalid of ['attempt', 'sha', 'repo', 'path', 'event', 'branch', 'name']) {
  test(`live CI ${invalid} mismatch cannot authorize continuation`, async () => {
    const f = apiFixture();
    const run = f.state.runs.get(6000);
    if (invalid === 'attempt') run.run_attempt = 2;
    if (invalid === 'sha') run.head_sha = FIX_ONE;
    if (invalid === 'repo') run.head_repository.full_name = 'external/repo';
    if (invalid === 'path') run.path = '.github/workflows/other.yml';
    if (invalid === 'event') run.event = 'pull_request';
    if (invalid === 'branch') run.head_branch = 'feature/unapproved';
    if (invalid === 'name') run.name = 'Unrelated checks';
    await assert.rejects(() => resolveSource(f), /does not match/);
    assert.equal(f.state.requests.length, 0);
  });
}

test('legacy workflow_run uses the same identity checks as explicit continuation', async () => {
  const f = apiFixture();
  f.context.eventName = 'workflow_run';
  f.context.payload.action = 'completed';
  f.context.payload.workflow_run = structuredClone(f.state.runs.get(6000));
  assert.deepEqual(sourceIdentity(f.context), {id: 6000, attempt: 1, sha: BASE, branch});
  assert.equal((await resolveSource(f)).pr.number, 50);
  f.context.payload.workflow_run.head_branch = 'ai/issue-1234-plan-v5-run-9999';
  await assert.rejects(() => resolveSource(f), /does not match/);
});

for (const changed of ['head', 'closed', 'author', 'repo', 'base']) {
  test(`a ${changed} PR makes duplicate or obsolete completion harmless`, async () => {
    const f = apiFixture();
    if (changed === 'head') f.state.pr.head.sha = FIX_ONE;
    if (changed === 'closed') f.state.pr.state = 'closed';
    if (changed === 'author') f.state.pr.user.login = 'external';
    if (changed === 'repo') f.state.pr.head.repo.full_name = 'external/repo';
    if (changed === 'base') f.state.pr.base.ref = 'main';
    assert.equal(await resolveSource(f), null);
    assert.equal(f.state.requests.length, 0);
  });
}

test('an ambiguous matching PR set is rejected rather than choosing a target', async () => {
  const f = apiFixture();
  f.state.open.push({...structuredClone(f.state.pr), number: 51});
  await assert.rejects(() => resolveSource(f), /More than one/);
});

test('a newer CI dispatch on the same commit supersedes an older failed attempt', async () => {
  const f = apiFixture();
  f.state.runs.set(6001, {...f.state.runs.get(6000), id: 6001,
    status: 'in_progress', conclusion: null});
  assert.equal(await resolveSource(f), null);
  assert.equal(f.state.requests.length, 0);
});

test('two successive repaired commits retain distinct CI identities and end in successful evidence', async () => {
  const f = apiFixture();
  const previous = [];
  for (const [sha, conclusion] of [[BASE, 'failure'], [FIX_ONE, 'failure'], [FIX_TWO, 'success']]) {
    f.state.pr.head.sha = sha;
    const run = await dispatchCiAndContinuation({...f, headSha: sha});
    Object.assign(f.state.runs.get(run.id), {status: 'completed', conclusion});
    const context = selectedContext(f, run);
    const source = await resolveSource({...f, context, waitForCompletion: true});
    assert.equal(source.run.head_sha, sha);
    assert.equal(source.run.conclusion, conclusion);
    for (const oldContext of previous) assert.equal(await resolveSource({...f, context: oldContext}), null);
    previous.push(context);
  }
  assert.equal(f.state.requests.filter(args => args.workflow_id === 'ci.yml').length, 3);
  assert.equal(f.state.requests.filter(args => args.workflow_id === 'opencode-ci-self-repair.yml').length, 3);
});

for (const [conclusion, draft, repair] of [['failure', true, 'true'],
  ['success', true, 'false'], ['failure', false, 'false'], ['cancelled', true, 'false']]) {
  test(`${conclusion} CI on ${draft ? 'draft' : 'ready'} PR routes to evidence and repair=${repair}`, async () => {
    const f = apiFixture();
    f.state.runs.get(6000).conclusion = conclusion;
    f.state.pr.draft = draft;
    await routeContinuation(f);
    assert.equal(f.state.outputs.eligible, 'true');
    assert.equal(f.state.outputs.repair, repair);
    assert.equal(f.state.outputs.ci_run_id, '6000');
    assert.equal(f.state.outputs.head_sha, BASE);
    assert.deepEqual(f.state.requests, [{owner: 'owner', repo: 'repo',
      workflow_id: 'ai-merge-readiness.yml', ref: 'main', inputs: {pr_number: '50'}}]);
  });
}

test('routing a duplicated completion after the head moved neither audits nor repairs stale code', async () => {
  const f = apiFixture();
  f.state.pr.head.sha = FIX_ONE;
  assert.equal(await routeContinuation(f), null);
  assert.equal(f.state.outputs.eligible, 'false');
  assert.equal(f.state.outputs.repair, 'false');
  assert.equal(f.state.requests.length, 0);
});
