'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {assertFreshPlanning, planningContext} = require('../../scripts/automation/planning.cjs');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');

function setup() {
  const previous = {id: 10, user: {login: 'github-actions[bot]'},
    body: '<!-- knx-issue-bot-state ' + JSON.stringify({version: 3, kind: 'plan',
      issue_digest: 'a'.repeat(64)}) + ' -->\nPrevious plan'};
  const trigger = {id: 20, user: {login: 'owner'}, body: '/ai answer Compare existing PRs'};
  const comments = [previous, trigger];
  const snapshot = {previous_plan_id: 10, previous_plan_sha256: hash(previous.body),
    latest_answer_id: 20, latest_answer_sha256: hash(trigger.body),
    trigger_comment_id: 20, trigger_comment_sha256: hash(trigger.body)};
  const context = {repo: {owner: 'owner', repo: 'repo'}, issue: {number: 137}};
  const github = {rest: {issues: {listComments() {}}}, paginate: async () => comments};
  return {comments, previous, trigger, snapshot, context, github};
}

test('unchanged source plan and owner request allow publication', async () => {
  await assertFreshPlanning(setup());
});

test('newer owner request blocks an older result even before its own model run', async () => {
  const state = setup();
  state.comments.push({id: 21, user: {login: 'owner'}, body: '/ai answer Different requirement'});
  await assert.rejects(assertFreshPlanning(state), /superseded/);
});

test('edited or deleted triggering request cannot publish its old proposal', async () => {
  for (const remove of [false, true]) {
    const state = setup();
    if (remove) state.comments.pop();
    else state.trigger.body = '/ai answer Changed after planning began';
    await assert.rejects(assertFreshPlanning(state), /changed|superseded/);
  }
});

test('newer bot plan or questions blocks stale publication', async () => {
  const state = setup();
  state.comments.push({...state.previous, id: 30});
  await assert.rejects(assertFreshPlanning(state), /previous bot plan changed/);
});

test('editing the previous bot plan blocks a result based on its old content', async () => {
  const state = setup();
  state.previous.body += '\nEdited after snapshot';
  await assert.rejects(assertFreshPlanning(state), /previous bot plan changed/);
});

test('a queued older command cannot publish using a newer request snapshot', async () => {
  const state = setup();
  state.snapshot.trigger_comment_id = 19;
  state.comments.push({...state.trigger, id: 19});
  await assert.rejects(assertFreshPlanning(state), /superseded/);
});

test('a request preceding an already published bot plan cannot publish again', async () => {
  const state = setup();
  state.previous.id = 30;
  state.snapshot.previous_plan_id = 30;
  await assert.rejects(assertFreshPlanning(state), /superseded/);
});

test('non-owner, empty and quoted answers do not invalidate a current request', async () => {
  const state = setup();
  state.comments.push(
    {id: 21, user: {login: 'other'}, body: '/ai answer Replace plan'},
    {id: 22, user: {login: 'owner'}, body: '/ai answer   '},
    {id: 23, user: {login: 'owner'}, body: '> /ai answer example'});
  await assertFreshPlanning(state);
});

test('label-triggered planning still rejects an owner request arriving during generation', async () => {
  const state = setup();
  state.snapshot.trigger_comment_id = 0;
  state.snapshot.trigger_comment_sha256 = null;
  await assertFreshPlanning(state);
  state.comments.push({...state.trigger, id: 21});
  await assert.rejects(assertFreshPlanning(state), /superseded/);
});

test('label-triggered planning rejects edited existing owner guidance', async () => {
  const state = setup();
  state.snapshot.trigger_comment_id = 0;
  state.snapshot.trigger_comment_sha256 = null;
  state.trigger.body = '/ai answer Changed while planning';
  await assert.rejects(assertFreshPlanning(state), /edited owner planning request/);
});

test('no freshness snapshot fails closed', async () => {
  const state = setup();
  state.snapshot = null;
  await assert.rejects(assertFreshPlanning(state), /Missing trusted planning snapshot/);
});

test('approval publication requires the same plan and no newer owner planning intent', async () => {
  const state = setup();
  state.trigger.body = '/ai approve v3';
  state.snapshot.latest_answer_id = 0;
  state.snapshot.latest_answer_sha256 = null;
  state.snapshot.trigger_comment_sha256 = hash(state.trigger.body);
  state.approval = true;
  await assertFreshPlanning(state);
  state.comments.push({id: 21, user: {login: 'owner'}, body: '/ai answer Replan first'});
  await assert.rejects(assertFreshPlanning(state), /superseded/);
});

test('approval cannot race past a newer plan or edit its original owner command', async () => {
  for (const changePlan of [true, false]) {
    const state = setup();
    state.trigger.body = '/ai approve v3';
    state.snapshot.latest_answer_id = 0;
    state.snapshot.latest_answer_sha256 = null;
    state.snapshot.trigger_comment_sha256 = hash(state.trigger.body);
    state.approval = true;
    if (changePlan) state.comments.push({...state.previous, id: 21});
    else state.trigger.body = '/ai approve v4';
    await assert.rejects(assertFreshPlanning(state), /changed|superseded/);
  }
});

test('five PR snapshots share one UTF-8 patch budget with explicit missing-evidence flags', async () => {
  const prs = Array.from({length: 5}, (_, index) => ({
    number: index + 1, title: 'Existing work', body: '#137 ' + '😀'.repeat(2500),
    head: {sha: 'a'.repeat(40), ref: 'existing-work'}, base: {ref: 'dev'}, draft: true
  }));
  const issue = {number: 137, title: 'Synthetic issue', body: 'Preserve existing behavior'};
  const methods = {listPRs() {}, listFiles() {}};
  const github = {rest: {issues: {get: async () => ({data: issue})},
    pulls: {list: methods.listPRs, listFiles: methods.listFiles}},
    paginate: async method => method === methods.listPRs ? prs :
      [{filename: 'feature.py', status: 'modified', patch: '😀'.repeat(16000)}]};
  const context = {repo: {owner: 'owner', repo: 'repo'}, issue: {number: 137}};

  const result = await planningContext({github, context});

  const patches = result.pull_requests.flatMap(pr => pr.files.map(f => f.patch));
  assert.equal(patches.reduce((bytes, patch) => bytes + Buffer.byteLength(patch), 0), 32000);
  assert.equal(result.pull_requests.length, 5);
  assert.ok(result.patch_bytes_omitted > 0);
  assert.ok(result.pull_requests.every(pr => pr.body_incomplete && pr.files[0].patch_incomplete));
  assert.ok(result.pull_requests.every(pr => Buffer.byteLength(pr.body) <= 2500));
  assert.ok(patches.every(patch => !patch.includes('\uFFFD')));
  assert.ok(Buffer.byteLength(JSON.stringify(result)) < 50000);
});
