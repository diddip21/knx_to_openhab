'use strict';

const crypto = require('node:crypto');
const PATCH_BUDGET_BYTES = 32000;

function utf8Prefix(text, budget) {
  let result = '';
  let used = 0;
  for (const character of text) {
    const size = Buffer.byteLength(character, 'utf8');
    if (used + size > budget) break;
    result += character;
    used += size;
  }
  return result;
}

function digest(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

function latestPlan(comments) {
  return comments.filter(c => {
    if ((c.user?.login || '').toLowerCase() !== 'github-actions[bot]') return false;
    const match = (c.body || '').match(/^<!-- knx-issue-bot-state (\{[^\n]*\}) -->/);
    if (!match) return false;
    try {
      const state = JSON.parse(match[1]);
      return Number.isInteger(state.version) && state.version > 0 && state.version <= 9999 &&
        ['questions', 'plan'].includes(state.kind) && /^[a-f0-9]{64}$/.test(state.issue_digest);
    } catch { return false; }
  }).sort((a, b) => b.id - a.id)[0];
}

// Recheck after model execution. A failed or queued newer request still supersedes old work.
async function assertFreshPlanning({github, context, snapshot, approval = false}) {
  if (!snapshot || !Number.isSafeInteger(snapshot.previous_plan_id) ||
      !Number.isSafeInteger(snapshot.latest_answer_id) ||
      !Number.isSafeInteger(snapshot.trigger_comment_id)) {
    throw new Error('Missing trusted planning snapshot; request a fresh plan');
  }
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner: context.repo.owner, repo: context.repo.repo,
    issue_number: context.issue.number, per_page: 100
  });
  const previous = latestPlan(comments);
  if ((previous?.id || 0) !== snapshot.previous_plan_id ||
      (previous ? digest(previous.body) : null) !== snapshot.previous_plan_sha256) {
    throw new Error('The previous bot plan changed while planning; refusing stale publication');
  }
  const answers = comments.filter(c =>
    (c.user?.login || '').toLowerCase() === context.repo.owner.toLowerCase() &&
    /^\/ai answer\s+\S[\s\S]*$/i.test((c.body || '').trim()));
  const latest = answers.reduce((current, c) => !current || c.id > current.id ? c : current, null);
  const latestAnswer = latest?.id || 0;
  if (latestAnswer !== snapshot.latest_answer_id ||
      (latest ? digest(latest.body) : null) !== snapshot.latest_answer_sha256) {
    throw new Error('A newer or edited owner planning request superseded this plan');
  }
  if (snapshot.trigger_comment_id) {
    const trigger = comments.find(c => c.id === snapshot.trigger_comment_id);
    if (!trigger || digest(trigger.body || '') !== snapshot.trigger_comment_sha256 ||
        (trigger.user?.login || '').toLowerCase() !== context.repo.owner.toLowerCase() ||
        (!approval && snapshot.trigger_comment_id !== latestAnswer) ||
        (approval && latestAnswer > snapshot.previous_plan_id) ||
        snapshot.trigger_comment_id <= snapshot.previous_plan_id) {
      throw new Error('The triggering owner request changed or was superseded');
    }
  } else if (approval) {
    throw new Error('Approval requires an unchanged owner command');
  }
}

// Same-repository API snapshots only. Content is untrusted reference data.
async function planningContext({github, context}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const {data: issue} = await github.rest.issues.get({...repo, issue_number: context.issue.number});
  const text = `${issue.title || ''}\n${issue.body || ''}`;
  const links = [...text.matchAll(/#([1-9][0-9]*)\b/g)].map(m => Number(m[1]));
  const prs = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
  const linked = prs.filter(p => links.includes(p.number) ||
    new RegExp(`#${issue.number}(?![0-9])`).test(p.body || '') ||
    p.head.ref.startsWith(`ai/issue-${issue.number}-`));
  const result = {pull_requests: [], omitted_prs: Math.max(0, linked.length - 5),
    patch_budget_bytes: PATCH_BUDGET_BYTES, patch_bytes_omitted: 0};
  let remainingBytes = PATCH_BUDGET_BYTES;
  for (const pr of linked.slice(0, 5)) {
    const files = await github.paginate(github.rest.pulls.listFiles,
      {...repo, pull_number: pr.number, per_page: 100});
    let budget = 16000;
    const body = utf8Prefix(pr.body || '', 2500);
    result.pull_requests.push({number: pr.number, head_sha: pr.head.sha, base: pr.base.ref,
      title: pr.title, body, body_incomplete: body !== (pr.body || ''), draft: pr.draft,
      files: files.slice(0, 40).map(f => {
        const patch = utf8Prefix(f.patch || '', Math.max(0, Math.min(budget, remainingBytes)));
        const bytes = Buffer.byteLength(patch, 'utf8');
        budget -= bytes;
        remainingBytes -= bytes;
        result.patch_bytes_omitted += Buffer.byteLength(f.patch || '', 'utf8') - bytes;
        return {path: f.filename, status: f.status, patch,
          patch_incomplete: !f.patch || patch.length !== f.patch.length};
      }), files_omitted: Math.max(0, files.length - 40)});
  }
  return result;
}

module.exports = {planningContext, assertFreshPlanning};
