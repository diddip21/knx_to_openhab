'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {assertLiveApproval} = require('../../scripts/automation/github.cjs');

const hash = value => crypto.createHash('sha256').update(value).digest('hex');

function fixture() {
  const repo = {owner: 'owner', repo: 'repo'};
  const issue = {number: 1234, state: 'open', title: 'Synthetic task', body: 'Scoped behavior',
    labels: [{name: 'ai:plan'}, {name: 'ai:approved'}]};
  const digest = hash(JSON.stringify([issue.title, issue.body]));
  const scope = {create: [], files: ['feature.py', 'tests/test_feature.py'], required: []};
  const comment = (id, login, body) => ({id, user: {login}, body,
    created_at: '2026-01-01T12:00:00Z', updated_at: '2026-01-01T12:00:00Z'});
  const plan = version => '<!-- knx-issue-bot-state ' +
    JSON.stringify({kind: 'plan', version, issue_digest: digest}) + ' -->\nApproved task';
  const command = version => `/ai implement v${version}\n` + JSON.stringify(scope);
  const comments = [comment(10, 'github-actions[bot]', plan(5)),
    comment(20, 'owner', '/ai approve v5'),
    comment(30, 'github-actions[bot]', '\u2705 **Plan v5 freigegeben.**'),
    comment(40, 'owner', command(5))];
  const item = {issue_number: 1234, version: 5, digest, scope,
    plan_comment_id: 10, approval_comment_id: 20, command_comment_id: 40,
    plan_sha256: hash(comments[0].body), command_sha256: hash(comments[3].body),
    scope_sha256: hash(JSON.stringify(scope))};
  const github = {rest: {issues: {get: async () => ({data: issue}),
    listComments: async () => comments}}, paginate: async (method, args) => method(args)};
  return {github, repo, item, comments, comment, plan, command};
}

test('a pending owner replan also revokes the independently verified publisher input', async () => {
  const f = fixture();
  await assertLiveApproval(f.github, f.repo, f.item);
  // The request arrives after the producer/publisher initially checked approval.
  f.comments.push(f.comment(45, 'OWNER', '  /AI answer Please replan; no implementation yet.  '));
  await assert.rejects(() => assertLiveApproval(f.github, f.repo, f.item), /replan request/);
});

test('a new approval of the old plan cannot dismiss an outstanding planning request', async () => {
  const f = fixture();
  f.comments.push(f.comment(45, 'owner', '/ai answer Review scope first'),
    f.comment(50, 'owner', '/ai approve v5'),
    f.comment(60, 'github-actions[bot]', '\u2705 **Plan v5 freigegeben.**'),
    f.comment(70, 'owner', f.command(5)));
  Object.assign(f.item, {approval_comment_id: 50, command_comment_id: 70,
    command_sha256: hash(f.command(5))});
  await assert.rejects(() => assertLiveApproval(f.github, f.repo, f.item), /replan request/);
});

test('edited planning requests continue to suspend publication', async () => {
  const f = fixture();
  const request = f.comment(45, 'owner', '/ai answer New acceptance criteria');
  request.updated_at = '2026-01-01T12:01:00Z';
  f.comments.push(request);
  await assert.rejects(() => assertLiveApproval(f.github, f.repo, f.item), /replan request/);
});

test('a fresh plan after the request requires and accepts fresh approval and start', async () => {
  const f = fixture();
  f.comments.push(f.comment(45, 'owner', '/ai answer Review scope first'),
    f.comment(50, 'github-actions[bot]', f.plan(6)),
    f.comment(60, 'owner', '/ai approve v6'),
    f.comment(70, 'github-actions[bot]', '\u2705 **Plan v6 freigegeben.**'),
    f.comment(80, 'owner', f.command(6)));
  await assert.rejects(() => assertLiveApproval(f.github, f.repo, f.item), /newer or different plan/);
  Object.assign(f.item, {version: 6, plan_comment_id: 50, approval_comment_id: 60,
    command_comment_id: 80, plan_sha256: hash(f.plan(6)), command_sha256: hash(f.command(6))});
  await assertLiveApproval(f.github, f.repo, f.item);
});

test('empty, quoted or third-party commands cannot revoke the owner task', async () => {
  for (const [login, body] of [['external', '/ai answer Different task'],
    ['github-actions[bot]', '/ai answer Example'], ['owner', '/ai answer \n'],
    ['owner', 'Use `/ai answer` when a plan needs revision'], ['owner', '/ai answers x']]) {
    const f = fixture();
    f.comments.push(f.comment(45, login, body));
    await assertLiveApproval(f.github, f.repo, f.item);
  }
});
