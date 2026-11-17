'use strict';

// Loaded only from the trusted default-branch checkout, never from a PR.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const branchPattern = /^ai\/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$/;
const hash = value => crypto.createHash('sha256').update(value, 'utf8').digest('hex');
const unedited = c => c && c.created_at === c.updated_at;
const canonical = value => JSON.stringify(Object.fromEntries(
  Object.keys(value).sort().map(key => [key, value[key]])));

const repoArgs = context => ({owner: context.repo.owner, repo: context.repo.repo});

async function history(github, repo, number) {
  const {data: issue} = await github.rest.issues.get({...repo, issue_number: number});
  const comments = await github.paginate(github.rest.issues.listComments,
    {...repo, issue_number: number, per_page: 100});
  if (comments.length > 2000) throw new Error('Issue history exceeds audit limit');
  return {issue, comments};
}

async function fetchSource({github, context, directory, mode}) {
  const repo = repoArgs(context);
  fs.mkdirSync(directory, {recursive: true});
  if (mode === 'implement') {
    const number = context.payload.issue?.number;
    if (context.eventName !== 'issue_comment' || context.payload.action !== 'created' ||
        context.payload.issue?.pull_request || !Number.isSafeInteger(number) || number < 1) {
      throw new Error('Invalid implementation event');
    }
    const source = await history(github, repo, number);
    fs.writeFileSync(path.join(directory, 'issue-current.json'), JSON.stringify(source.issue));
    fs.writeFileSync(path.join(directory, 'issue-comments.json'), JSON.stringify(source.comments));
    return source;
  }
  if (mode !== 'repair') throw new Error('Unknown source mode');
  const expected = context.payload.workflow_run;
  const match = branchPattern.exec(expected?.head_branch || '');
  if (context.eventName !== 'workflow_run' || !match) throw new Error('Invalid repair event');
  const {data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: expected.id});
  const open = await github.paginate(github.rest.pulls.list,
    {...repo, state: 'open', head: `${repo.owner}:${expected.head_branch}`, per_page: 100});
  const prs = open.filter(p => p.head.ref === expected.head_branch && p.base.ref === 'dev');
  if (prs.length !== 1) throw new Error('Exactly one matching development PR is required');
  const pr = prs[0];
  const source = await history(github, repo, Number(match[1]));
  const commits = await github.paginate(github.rest.pulls.listCommits,
    {...repo, pull_number: pr.number, per_page: 100});
  const result = {...source, run, pr, commits};
  fs.writeFileSync(path.join(directory, 'repair-source.json'), JSON.stringify(result));
  return result;
}

async function assertLiveApproval(github, repo, item) {
  const {issue, comments} = await history(github, repo, item.issue_number);
  const labels = new Set(issue.labels.map(l => typeof l === 'string' ? l : l.name));
  if (issue.state !== 'open' || issue.pull_request || !labels.has('ai:plan') ||
      !labels.has('ai:approved') || labels.has('ai:waiting') ||
      hash(JSON.stringify([issue.title || '', issue.body || ''])) !== item.digest) {
    throw new Error('Issue approval was changed or revoked');
  }
  const byId = id => comments.find(c => c.id === id);
  const command = byId(item.command_comment_id);
  const approval = byId(item.approval_comment_id);
  const plan = byId(item.plan_comment_id);
  const isOwner = c => c?.user?.login?.toLowerCase() === repo.owner.toLowerCase();
  if (!isOwner(command) || !isOwner(approval) || !unedited(command) || !unedited(approval) ||
      !unedited(plan) || plan.user?.login !== 'github-actions[bot]' ||
      command.id <= approval.id || approval.id <= plan.id ||
      approval.body.trim().toLowerCase() !== `/ai approve v${item.version}` ||
      hash(command.body.trim()) !== item.command_sha256 || hash(plan.body) !== item.plan_sha256) {
    throw new Error('Owner command, plan or approval changed before publication');
  }
  const raw = command.body.trim().split('\n').slice(1).join('\n').trim();
  const fenced = /^```json\s*\n([\s\S]*)\n```$/.exec(raw);
  const scope = JSON.parse(fenced ? fenced[1] : raw);
  if (!scope || typeof scope !== 'object' || Object.keys(scope).some(
      key => !['files', 'create', 'required'].includes(key))) throw new Error('Invalid live scope');
  const normalized = {};
  for (const key of ['files', 'create', 'required']) {
    const entries = scope[key] || [];
    if (!Array.isArray(entries) || entries.some(p => typeof p !== 'string')) {
      throw new Error('Invalid live scope paths');
    }
    normalized[key] = [...entries].sort();
  }
  if (canonical(normalized) !== canonical(item.scope) ||
      hash(canonical(normalized)) !== item.scope_sha256) {
    throw new Error('Verified scope differs from live owner command');
  }
  const states = comments.filter(c => c.user?.login === 'github-actions[bot]')
    .map(c => {
      const m = /^<!-- knx-issue-bot-state (\{[^\n]*\}) -->/.exec(c.body || '');
      return m ? {comment: c, state: JSON.parse(m[1])} : null;
    }).filter(Boolean).sort((a, b) => b.comment.id - a.comment.id);
  const latest = states[0];
  if (!latest || latest.comment.id !== plan.id || latest.state.kind !== 'plan' ||
      latest.state.version !== item.version || latest.state.issue_digest !== item.digest) {
    throw new Error('A newer or different plan is pending');
  }
  if (!comments.some(c => c.id > approval.id && c.id < command.id && unedited(c) &&
      c.user?.login === 'github-actions[bot]' &&
      c.body.startsWith(`\u2705 **Plan v${item.version} freigegeben.**`))) {
    throw new Error('Approval receipt disappeared');
  }
}

function taskReference(item) {
  return Object.fromEntries(['issue_number', 'version', 'command_comment_id', 'command_sha256',
    'plan_sha256', 'scope_sha256', 'base_commit_sha'].map(k => [k, item[k]]));
}

function validateVerified(item, context, mode) {
  if (!['implement', 'repair'].includes(mode)) throw new Error('Unknown publication mode');
  const repository = `${context.repo.owner}/${context.repo.repo}`;
  if (item.mode !== mode || item.repository !== repository || item.run_id !== context.runId ||
      !Number.isSafeInteger(item.issue_number) || item.issue_number < 1 ||
      !Number.isSafeInteger(item.version) || item.version < 1 ||
      !/^[0-9a-f]{40}$/.test(item.base_commit_sha) || !/^[0-9a-f]{40}$/.test(item.trusted_sha)) {
    throw new Error('Invalid verified task metadata');
  }
  if (mode === 'implement' && (context.payload.issue?.number !== item.issue_number ||
      context.payload.comment?.id !== item.command_comment_id ||
      context.actor.toLowerCase() !== context.repo.owner.toLowerCase())) {
    throw new Error('Implementation event does not match verified owner command');
  }
  if (mode === 'repair') {
    const expected = context.payload.workflow_run;
    const match = branchPattern.exec(item.branch || '');
    if (!match || Number(match[1]) !== item.issue_number || Number(match[2]) !== item.version ||
        expected?.head_branch !== item.branch || expected.head_sha !== item.base_commit_sha ||
        expected.id !== item.failed_run_id || ![1, 2].includes(item.attempt)) {
      throw new Error('Invalid verified repair metadata');
    }
  }
  const allowed = new Set(item.scope?.files || []);
  if (!Array.isArray(item.files) || !item.files.length || item.files.length > (mode === 'repair' ? 12 : 20)) {
    throw new Error('Invalid verified file count');
  }
  const paths = new Set();
  let size = 0;
  for (const file of item.files) {
    if (!allowed.has(file.path) || paths.has(file.path) || !['100644', '100755'].includes(file.mode)) {
      throw new Error('Verified file scope or mode violation');
    }
    paths.add(file.path);
    const bytes = Buffer.from(file.content_b64, 'base64');
    size += bytes.length;
    if (!bytes.length || bytes.length > 300000 || size > 1250000 ||
        hash(bytes) !== file.sha256 || bytes.toString('base64') !== file.content_b64) {
      throw new Error('Verified file digest or size mismatch');
    }
  }
}

async function assertHead(github, repo, item, mode, defaultBranch) {
  const {data: trusted} = await github.rest.repos.getBranch({...repo, branch: defaultBranch});
  if (trusted.commit.sha !== item.trusted_sha) throw new Error('Trusted default branch moved');
  if (mode === 'implement') {
    const {data: dev} = await github.rest.repos.getBranch({...repo, branch: 'dev'});
    if (dev.commit.sha !== item.base_commit_sha) throw new Error('Development base moved');
    const {data: comparison} = await github.rest.repos.compareCommits(
      {...repo, base: item.trusted_sha, head: item.base_commit_sha});
    if (comparison.behind_by !== 0) throw new Error('dev must contain trusted main');
    return;
  }
  const {data: pr} = await github.rest.pulls.get({...repo, pull_number: item.pr_number});
  const {data: ref} = await github.rest.git.getRef({...repo, ref: `heads/${item.branch}`});
  if (pr.state !== 'open' || !pr.draft || pr.user.login !== 'github-actions[bot]' ||
      pr.base.ref !== 'dev' || pr.head.ref !== item.branch ||
      pr.head.repo?.full_name !== item.repository || pr.head.sha !== item.base_commit_sha ||
      ref.object.sha !== item.base_commit_sha) throw new Error('Draft PR changed before repair');
  const {data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: item.failed_run_id});
  if (run.run_attempt !== item.failed_run_attempt || run.status !== 'completed' ||
      run.conclusion !== 'failure' || run.head_sha !== item.base_commit_sha ||
      run.path !== '.github/workflows/ci.yml' || run.event !== 'workflow_dispatch') {
    throw new Error('CI run changed before repair');
  }
}

async function publish({github, context, core, verifiedPath, mode}) {
  // This file must be produced by trusted Python recheck in THIS fresh job.
  // Never call publish on the raw artifact downloaded from the model job.
  const item = JSON.parse(fs.readFileSync(verifiedPath, 'utf8'));
  validateVerified(item, context, mode);
  const repo = repoArgs(context);
  const defaultBranch = context.payload.repository.default_branch;
  const head = mode === 'repair' ? item.branch :
    `ai/issue-${item.issue_number}-plan-v${item.version}-run-${context.runId}`;
  await assertLiveApproval(github, repo, item);
  await assertHead(github, repo, item, mode, defaultBranch);
  if (mode === 'implement') {
    const open = await github.paginate(github.rest.pulls.list, {...repo, state: 'open', per_page: 100});
    const prefix = `ai/issue-${item.issue_number}-plan-v${item.version}-run-`;
    const existing = open.find(p => p.head.repo?.full_name === item.repository && p.head.ref.startsWith(prefix));
    if (existing) {
      const saved = /<!-- ai-task: (\{[^\n]*\}) -->/.exec(existing.body || '');
      if (existing.head.ref !== head || !saved ||
          JSON.stringify(JSON.parse(saved[1])) !== JSON.stringify(taskReference(item))) {
        throw new Error(`An implementation PR for this plan already exists: #${existing.number}`);
      }
      // A rerun of the same command resumes CI, never republishes or overwrites code.
      await github.rest.actions.createWorkflowDispatch({...repo, workflow_id: 'ci.yml', ref: head});
      core.info(`Existing Draft PR #${existing.number}; CI resumed without code changes`);
      return {pr: existing.number, reused: true};
    }
  }
  const entries = [];
  for (const file of item.files) {
    const {data: blob} = await github.rest.git.createBlob(
      {...repo, content: file.content_b64, encoding: 'base64'});
    entries.push({path: file.path, mode: file.mode, type: 'blob', sha: blob.sha});
  }
  const {data: base} = await github.rest.git.getCommit({...repo, commit_sha: item.base_commit_sha});
  const {data: tree} = await github.rest.git.createTree({...repo, base_tree: base.tree.sha, tree: entries});
  const message = mode === 'repair'
    ? `fix(ai-ci): issue ${item.issue_number} plan v${item.version} attempt ${item.attempt}`
    : `feat(ai): issue ${item.issue_number} plan v${item.version}`;
  const {data: commit} = await github.rest.git.createCommit({...repo,
    message: `${message}\n\nAI-command: ${item.command_comment_id}\nScope-SHA256: ${item.scope_sha256}`,
    tree: tree.sha, parents: [item.base_commit_sha]});
  // Recheck after creating inert Git objects, immediately before moving any ref.
  await assertLiveApproval(github, repo, item);
  await assertHead(github, repo, item, mode, defaultBranch);
  let prNumber = item.pr_number;
  if (mode === 'repair') {
    await github.rest.git.updateRef({...repo, ref: `heads/${head}`, sha: commit.sha, force: false});
  } else {
    await github.rest.git.createRef({...repo, ref: `refs/heads/${head}`, sha: commit.sha});
    const {data: pr} = await github.rest.pulls.create({...repo,
      title: `feat(ai): implement issue #${item.issue_number} (plan v${item.version})`,
      head, base: 'dev', draft: true,
      body: `Owner-approved issue #${item.issue_number}, plan v${item.version}.\n\n` +
        `Generated candidate; review and fresh CI required. No automatic merge.\n` +
        `Owner-approved files: ${item.scope.files.map(p => '`' + p + '`').join(', ')}.\n` +
        `No test results, screenshots or physical-device validation are claimed by generation.\n\n` +
        `<!-- ai-implementation-command: ${item.command_comment_id} -->\n` +
        `<!-- ai-task: ${JSON.stringify(taskReference(item))} -->\n\n` +
        `Run: https://github.com/${item.repository}/actions/runs/${context.runId}`});
    prNumber = pr.number;
  }
  await github.rest.actions.createWorkflowDispatch({...repo, workflow_id: 'ci.yml', ref: head});
  core.info(`Published ${mode} to PR #${prNumber}; full CI explicitly dispatched`);
  await core.summary.addRaw(`PR #${prNumber}: ${mode}, commit ${commit.sha}. No merge performed.\n`).write();
  return {pr: prNumber, sha: commit.sha, reused: false};
}

module.exports = {fetchSource, publish, validateVerified, assertLiveApproval, taskReference};
