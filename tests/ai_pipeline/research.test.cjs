'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {sourceRequests, collectEvidence} = require('../../scripts/automation/research.cjs');
const {planningContext} = require('../../scripts/automation/planning.cjs');
const repo = {owner: 'owner', repo: 'repo'};
const sha = 'a'.repeat(40);
const source = 'https://github.com/vendor/addon/blob/4.2.0/Bridge.java';

test('only pinned files, same-repository commits and official documentation are fetched', () => {
  const requests = sourceRequests([
    source, 'https://github.com/owner/repo/commit/' + sha,
    'https://www.openhab.org/addons/integrations/homekit/#multiple-instances',
    'https://github.com/vendor/addon/blob/main/Bridge.java',
    'https://github.com/foreign/repo/commit/' + sha,
    'https://www.openhab.org.evil.test/addons/integrations/homekit/',
    'https://user:password@www.openhab.org/addons/integrations/homekit/',
    'http://127.0.0.1/private',
  ].join('\n'), repo);
  assert.deepEqual(requests.map(x => x.kind), ['file', 'commit', 'documentation']);
});

test('version tags resolve to a commit and the entire file is materialized outside the prompt', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'planner-research-'));
  t.after(() => fs.rmSync(directory, {recursive: true}));
  let contentRef;
  const content = 'Full original source\n'.repeat(10000);
  const github = {rest: {repos: {
    getCommit: async () => ({data: {sha}}),
    getContent: async args => {
      contentRef = args.ref;
      return {data: {encoding: 'base64', content: Buffer.from(content).toString('base64')}};
    },
  }}};
  const result = await collectEvidence({github, repo, text: source, evidenceDirectory: directory});
  assert.equal(contentRef, sha);
  assert.equal(result.sources[0].status, 'available');
  assert.equal(result.sources[0].revision, sha);
  assert.ok(fs.readFileSync(path.join(directory, path.basename(result.sources[0].file)), 'utf8').endsWith(content));
  assert.ok(!JSON.stringify(result).includes('Full original source'));
});

test('redirects are never followed and failures remain explicit', async () => {
  let requests = 0;
  const result = await collectEvidence({github: {}, repo,
    text: 'https://www.openhab.org/addons/integrations/homekit/',
    fetchDocument: async (url, options) => {
      requests++;
      assert.equal(options.redirect, 'manual');
      assert.equal(options.headers, undefined);
      return {ok: false};
    }});
  assert.equal(requests, 1);
  assert.equal(result.sources[0].status, 'unavailable');
});

test('oversized sources are reported instead of silently shortened', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'planner-research-'));
  t.after(() => fs.rmSync(directory, {recursive: true}));
  const github = {rest: {repos: {
    getCommit: async () => ({data: {sha}}),
    getContent: async () => ({data: {encoding: 'base64', content: Buffer.from('x'.repeat(256001)).toString('base64')}}),
  }}};
  const result = await collectEvidence({github, repo, text: source, evidenceDirectory: directory});
  assert.equal(result.sources[0].status, 'size_limit');
  assert.equal(result.total_bytes, 0);
  assert.equal(fs.readdirSync(directory).length, 0);
});

test('a linked closed PR is included with its exact SHA and merged status', async () => {
  const list = () => {};
  const github = {rest: {
    issues: {get: async () => ({data: {title: 'Compare #12', body: ''}})},
    pulls: {list, get: async args => {
      assert.equal(args.pull_number, 12);
      return {data: {number: 12, state: 'closed', merged: true, head: {sha, ref: 'old'},
        base: {ref: 'dev'}, title: 'Prior work', body: ''}};
    }, listFiles: () => {}},
  }, paginate: async method => method === list ? [] : [{filename: 'feature.py', patch: 'old fix'}]};
  const result = await planningContext({github, context: {repo, issue: {number: 19}}});
  assert.equal(result.pull_requests.length, 1);
  assert.equal(result.pull_requests[0].head_sha, sha);
  assert.equal(result.pull_requests[0].state, 'closed');
  assert.equal(result.pull_requests[0].merged, true);
  assert.deepEqual(result.unresolved_pr_links, []);
});

test('missing historical PR references are exposed', async () => {
  const github = {rest: {issues: {get: async () => ({data: {title: '#12', body: ''}})},
    pulls: {list() {}, get: async () => {throw Error('not found');}}}, paginate: async () => []};
  const result = await planningContext({github, context: {repo, issue: {number: 19}}});
  assert.deepEqual(result.unresolved_pr_links, [12]);
});
