'use strict';

// These are fake API state machines, not live GitHub or live-model evidence.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {publish, fetchSource, taskReference} = require('../../scripts/automation/github.cjs');
const readiness = require('../../scripts/automation/readiness.cjs');
const {report} = require('../../scripts/automation/status.cjs');
const {planningContext} = require('../../scripts/automation/planning.cjs');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const BASE = 'a'.repeat(40);
const TRUSTED = 'b'.repeat(40);
const RESULT = 'c'.repeat(40);

function setup(t, number = 89, version = 3, repair = false) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'ai-publisher-test-'));
  t.after(() => fs.rmSync(temp, {recursive: true, force: true}));
  const scope = {files: ['feature.py', 'tests/test_feature.py'], create: [], required: []};
  const issue = {number, title: 'Synthetic', body: 'Test task', state: 'open',
    labels: [{name: 'ai:plan'}, {name: 'ai:approved'}]};
  const digest = hash(JSON.stringify([issue.title, issue.body]));
  const comments = [
    {id: 10, user: {login: 'github-actions[bot]'},
      body: '<!-- knx-issue-bot-state ' + JSON.stringify({kind: 'plan', version, issue_digest: digest}) + ' -->\nPlan'},
    {id: 20, user: {login: 'owner'}, body: `/ai approve v${version}`},
    {id: 30, user: {login: 'github-actions[bot]'}, body: `\u2705 **Plan v${version} freigegeben.**`},
    {id: 40, user: {login: 'owner'}, body: `/ai implement v${version}\n` + JSON.stringify(scope)}
  ];
  comments.forEach((c, i) => { c.created_at = c.updated_at = `2026-01-01T00:00:0${i}Z`; });
  const branch = `ai/issue-${number}-plan-v${version}-run-1000`;
  const run = {id: 6000, run_attempt: 1, name: 'CI', path: '.github/workflows/ci.yml',
    event: 'workflow_dispatch', status: 'completed', conclusion: 'failure', head_sha: BASE,
    head_branch: branch, head_repository: {full_name: 'owner/repo'}};
  const context = {actor: 'owner', runId: repair ? 2000 : 1000,
    eventName: repair ? 'workflow_run' : 'issue_comment', repo: {owner: 'owner', repo: 'repo'},
    payload: {action: repair ? 'completed' : 'created', repository: {default_branch: 'main'},
      issue, comment: comments[3], workflow_run: {...run}}};
  const item = {issue_number: number, version, mode: repair ? 'repair' : 'implement',
    repository: 'owner/repo', run_id: context.runId, base_commit_sha: BASE, trusted_sha: TRUSTED,
    digest, plan_comment_id: 10, approval_comment_id: 20, command_comment_id: 40,
    command_sha256: hash(comments[3].body.trim()), plan_sha256: hash(comments[0].body), scope,
    scope_sha256: hash(JSON.stringify({create: [], files: scope.files, required: []})),
    files: scope.files.map(p => { const content = Buffer.from(p.endsWith('test_feature.py') ? 'assert True\n' : 'value = 1\n');
      return {path: p, mode: '100644', content_b64: content.toString('base64'), sha256: hash(content)}; })};
  if (repair) Object.assign(item, {branch, pr_number: 50, failed_run_id: 6000,
    failed_run_attempt: 1, attempt: 1});
  const pr = {number: 50, state: 'open', draft: true, user: {login: 'github-actions[bot]'},
    base: {ref: 'dev'}, head: {ref: branch, sha: BASE, repo: {full_name: 'owner/repo'}},
    mergeable: true, body: '<!-- ai-implementation-command: 40 -->\n<!-- ai-task: ' +
      JSON.stringify(taskReference(item)) + ' -->'};
  const state = {open: repair ? [pr] : [], pr, mutations: [], dispatches: [], blobs: [],
    head: BASE, afterBlob: null, graphPage: 0, statusComments: []};
  const github = {rest: {
    issues: {get: async () => ({data: issue}), listComments: async () => comments,
      createComment: async args => {state.statusComments.push(args); comments.push({id: 80,
        user: {login:'github-actions[bot]'}, body:args.body});},
      updateComment: async args => {state.statusComments.push(args); comments.find(c=>c.id===args.comment_id).body=args.body;}},
    repos: {getBranch: async ({branch: b}) => ({data: {commit: {sha: b === 'main' ? TRUSTED : BASE}}}),
      compareCommits: async () => ({data: {behind_by: 0}})},
    pulls: {list: async () => state.open, get: async () => ({data: state.pr}),
      listCommits: async () => [{commit: {message: `feat(ai): issue ${number} plan v${version}`}}],
      listReviews: async () => [], listFiles: async () => [{filename: 'feature.py', status: 'modified'}],
      create: async args => { state.mutations.push(['pr', args]);
        state.pr = {...pr, body: args.body, head: {...pr.head, sha: state.head}};
        state.open.push(state.pr); return {data: state.pr}; }},
    actions: {getWorkflowRun: async () => ({data: run}),
      listJobsForWorkflowRun: async () => ({data:{jobs:[]}}),
      listWorkflowRunArtifacts: async () => ({data:{artifacts:[{id:90, name:'ui-screenshots-and-reports', expired:false}]}}),
      createWorkflowDispatch: async args => {state.dispatches.push(args);}},
    checks: {listForRef: async () => []},
    git: {createBlob: async args => {state.blobs.push(args); if (state.afterBlob) state.afterBlob();
        return {data: {sha: hash(args.content).slice(0, 40)}};},
      getCommit: async () => ({data: {tree: {sha: 'base-tree'}}}),
      createTree: async args => {state.mutations.push(['tree', args]); return {data: {sha: 'new-tree'}};},
      createCommit: async args => {state.mutations.push(['commit', args]); return {data: {sha: RESULT}};},
      createRef: async args => {state.mutations.push(['ref', args]); state.head = args.sha;},
      getRef: async () => ({data: {object: {sha: state.head}}}),
      updateRef: async args => {state.mutations.push(['update', args]); state.head = args.sha;
        state.pr.head.sha = args.sha;}}
  }, paginate: async (method, args) => method(args),
    graphql: async () => ({repository: {pullRequest: {reviewThreads: {
      nodes: [{isResolved: true}], pageInfo: {hasNextPage: false, endCursor: null}
    }}}})};
  const core = {info() {}, setOutput() {}, summary: {addRaw() {return this;}, async write() {}}};
  const verifiedPath = path.join(temp, 'task-verified.json');
  const save = () => fs.writeFileSync(verifiedPath, JSON.stringify(item));
  save();
  return {github, context, core, verifiedPath, mode: item.mode, temp, item, state, issue, comments, run, save};
}

for (const [number, version] of [[89, 3], [1234, 5]]) {
  test(`generic publisher creates only a Draft PR for issue ${number}`, async t => {
    const f = setup(t, number, version);
    const result = await publish(f);
    assert.equal(result.pr, 50);
    const pr = f.state.mutations.find(([kind]) => kind === 'pr')[1];
    assert.equal(pr.base, 'dev');
    assert.equal(pr.draft, true);
    assert.equal(f.state.dispatches[0].workflow_id, 'ci.yml');
    assert.equal(f.state.dispatches[0].ref, `ai/issue-${number}-plan-v${version}-run-1000`);
    assert.ok(f.state.mutations.filter(([kind]) => kind === 'ref').every(([, args]) => args.ref.startsWith('refs/heads/ai/')));
    const blobs = f.state.blobs.length;
    assert.equal((await publish(f)).reused, true);
    assert.equal(f.state.blobs.length, blobs);
    assert.equal(f.state.mutations.filter(([kind]) => kind === 'pr').length, 1);
  });
  test(`generic repair updates only the expected branch for issue ${number}`, async t => {
    const f = setup(t, number, version, true);
    await publish(f);
    const update = f.state.mutations.find(([kind]) => kind === 'update')[1];
    assert.equal(update.force, false);
    assert.equal(update.ref, `heads/ai/issue-${number}-plan-v${version}-run-1000`);
    assert.equal(f.state.mutations.some(([kind]) => kind === 'pr'), false);
    assert.equal(f.state.dispatches.length, 1);
  });
}

for (const attack of ['digest', 'scope', 'repository', 'actor', 'run', 'file-path', 'mode', 'revoked']) {
  test(`publisher rejects ${attack} before writing`, async t => {
    const f = setup(t);
    if (attack === 'digest') f.item.files[0].sha256 = '0'.repeat(64);
    if (attack === 'scope') f.item.scope.files.push('other.py');
    if (attack === 'repository') f.item.repository = 'other/repo';
    if (attack === 'actor') f.context.actor = 'other';
    if (attack === 'run') f.item.run_id++;
    if (attack === 'file-path') f.item.files[0].path = '.github/workflows/ci.yml';
    if (attack === 'mode') f.item.files[0].mode = '120000';
    if (attack === 'revoked') f.issue.labels = [];
    f.save();
    await assert.rejects(() => publish(f));
    assert.equal(f.state.mutations.length, 0);
    assert.equal(f.state.blobs.length, 0);
  });
}

test('revocation during Git object creation prevents branch mutation', async t => {
  const f = setup(t);
  f.state.afterBlob = () => {f.issue.labels = [];};
  await assert.rejects(() => publish(f));
  assert.equal(f.state.mutations.some(([kind]) => ['ref', 'update', 'pr'].includes(kind)), false);
  assert.equal(f.state.dispatches.length, 0);
});

test('short start is independently verified by the publisher', async t => {
  const f = setup(t);
  const marker = {kind:'plan', version:3, issue_digest:f.item.digest, scope:f.item.scope};
  f.comments[0].body = '<!-- knx-issue-bot-state ' + JSON.stringify(marker) + ' -->\nPlan';
  f.comments[3].body = '/ai start v3';
  f.item.plan_sha256 = hash(f.comments[0].body);
  f.item.command_sha256 = hash(f.comments[3].body);
  f.save();
  await publish(f);
  assert.equal(f.state.dispatches.length, 1);
});

test('short start cannot silently reuse a legacy unscoped plan', async t => {
  const f = setup(t);
  f.comments[3].body = '/ai start v3';
  f.item.command_sha256 = hash(f.comments[3].body);
  f.save();
  await assert.rejects(() => publish(f), /Invalid live scope/);
  assert.equal(f.state.blobs.length, 0);
});

test('CI status updates one comment and ignores a stale PR SHA', async t => {
  const f = setup(t, 1234, 5, true);
  await report(f);
  assert.match(f.state.statusComments[0].body, /0\/2/);
  assert.match(f.state.statusComments[0].body, /workflow_dispatch/);
  assert.match(f.state.statusComments[0].body, /artifacts\/90/);
  f.run.conclusion = 'success';
  await report(f);
  assert.equal(f.state.statusComments[1].comment_id, 80);
  assert.match(f.state.statusComments[1].body, /CI bestanden/);
  f.state.pr.head.sha = RESULT;
  await report(f);
  assert.equal(f.state.statusComments.length, 2);
  assert.equal(f.state.mutations.length, 0);
});

test('failed start gives owner instructions without exposing raw logs', async t => {
  const f = setup(t);
  await report({...f, phase:'failure'});
  const message = f.state.statusComments[0].body;
  assert.match(message, /approve.*start/);
  assert.match(message, /vollständigen JSON/);
  assert.match(message, /neuen Kommentar/);
  assert.equal(f.state.mutations.length, 0);
});

test('status reporter ignores foreign runs and does not regress from CI to publication', async t => {
  const f = setup(t, 1234, 5, true);
  f.context.payload.workflow_run.head_repository.full_name = 'foreign/repo';
  await report(f);
  assert.equal(f.state.statusComments.length, 0);
  f.context.payload.workflow_run.head_repository.full_name = 'owner/repo';
  await report(f);
  f.context.eventName = 'issue_comment';
  await report({...f, phase:'published'});
  assert.equal(f.state.statusComments.length, 1);
});

test('repair failure explains stop and a delayed CI event cannot erase it', async t => {
  const f = setup(t, 1234, 5, true);
  await report({...f, phase:'repair-failure'});
  assert.match(f.state.statusComments[0].body, /KI-Reparatur angehalten/);
  await report(f);
  assert.equal(f.state.statusComments.length, 1);
});

test('planning receives existing PR metadata and bounded patches', async t => {
  const f = setup(t);
  f.context.issue = {number:89};
  f.issue.body = 'Compare existing #50';
  f.state.open = [{...f.state.pr, title:'Existing implementation'}];
  f.github.rest.pulls.listFiles = async () => [{filename:'feature.py', status:'modified', patch:'x'.repeat(20000)}];
  const result = await planningContext(f);
  assert.equal(result.pull_requests[0].head_sha, BASE);
  assert.equal(result.pull_requests[0].files[0].patch.length, 16000);
  assert.equal(result.pull_requests[0].files[0].patch_incomplete, true);
});

test('stale repair HEAD and changed run attempt cannot publish', async t => {
  const f = setup(t, 1234, 5, true);
  f.state.head = 'd'.repeat(40);
  await assert.rejects(() => publish(f), /Draft PR changed/);
  assert.equal(f.state.mutations.length, 0);
  f.state.head = BASE;
  f.run.run_attempt = 2;
  await assert.rejects(() => publish(f), /CI run changed/);
});

test('another command cannot create a duplicate PR for the same plan', async t => {
  const f = setup(t);
  f.state.open.push({...f.state.pr, head: {...f.state.pr.head, ref: 'ai/issue-89-plan-v3-run-999'}});
  await assert.rejects(() => publish(f), /already exists/);
  assert.equal(f.state.mutations.length, 0);
});

test('source collector uses event issue and branch numbers, never a fixed pilot', async t => {
  const f = setup(t, 1234, 5);
  await fetchSource({...f, directory: f.temp, mode: 'implement'});
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.temp, 'issue-current.json'))).number, 1234);
  f.context.eventName = 'workflow_run';
  f.state.open = [f.state.pr];
  await fetchSource({...f, directory: f.temp, mode: 'repair'});
  const source = JSON.parse(fs.readFileSync(path.join(f.temp, 'repair-source.json')));
  assert.equal(source.issue.number, 1234);
  assert.equal(source.run.id, 6000);
});

test('readiness collector follows current PR on CI completion and never writes GitHub', async t => {
  const f = setup(t, 1234, 5, true);
  const output = await readiness({...f, directory: f.temp});
  assert.equal(output.pr.head_sha, BASE);
  assert.equal(output.issue.number, 1234);
  assert.equal(output.unresolved_threads, 0);
  assert.equal(f.state.mutations.length, 0);
  assert.equal(f.state.dispatches.length, 0);
});

test('readiness paginates review threads and reports unresolved threads', async t => {
  const f = setup(t, 1234, 5, true);
  let pages = 0;
  f.github.graphql = async () => ({repository: {pullRequest: {reviewThreads: {
    nodes: [{isResolved: pages !== 0}], pageInfo: {hasNextPage: pages++ === 0, endCursor: 'next'}
  }}}});
  const output = await readiness({...f, directory: f.temp});
  assert.equal(pages, 2);
  assert.equal(output.unresolved_threads, 1);
});
