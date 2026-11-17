'use strict';

const fs = require('node:fs');
const path = require('node:path');
const branchPattern = /^ai\/issue-([1-9][0-9]*)-plan-v([1-9][0-9]*)-run-([1-9][0-9]*)$/;

module.exports = async function snapshot({github, context, core, directory}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  let number = context.eventName === 'workflow_dispatch'
    ? Number(context.payload.inputs?.pr_number) : context.payload.pull_request?.number;
  if (context.eventName === 'workflow_run') {
    const expected = context.payload.workflow_run;
    if (!branchPattern.test(expected.head_branch || '') ||
        expected.head_repository?.full_name !== `${repo.owner}/${repo.repo}`) return null;
    const {data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: expected.id});
    if (run.path !== '.github/workflows/ci.yml') return null;
    const prs = await github.paginate(github.rest.pulls.list,
      {...repo, state: 'open', head: `${repo.owner}:${expected.head_branch}`, per_page: 100});
    const matching = prs.filter(p => p.head.ref === expected.head_branch && p.base.ref === 'dev');
    if (matching.length !== 1) return null;
    number = matching[0].number;
  }
  if (!Number.isSafeInteger(number) || number < 1) throw new Error('Invalid PR number');
  const {data: pr} = await github.rest.pulls.get({...repo, pull_number: number});
  const match = branchPattern.exec(pr.head.ref);
  let issue = {};
  let comments = [];
  if (match) {
    const issue_number = Number(match[1]);
    ({data: issue} = await github.rest.issues.get({...repo, issue_number}));
    comments = await github.paginate(github.rest.issues.listComments, {...repo, issue_number, per_page: 100});
  }
  const [reviews, files, checks] = await Promise.all([
    github.paginate(github.rest.pulls.listReviews, {...repo, pull_number: number, per_page: 100}),
    github.paginate(github.rest.pulls.listFiles, {...repo, pull_number: number, per_page: 100}),
    github.paginate(github.rest.checks.listForRef,
      {...repo, ref: pr.head.sha, per_page: 100, filter: 'latest'})
  ]);
  if (comments.length > 2000 || files.length > 500 || reviews.length > 2000 || checks.length > 1000) {
    throw new Error('Snapshot exceeds evidence limits');
  }
  const query = `query($owner:String!, $name:String!, $number:Int!, $after:String) {
    repository(owner:$owner,name:$name) { pullRequest(number:$number) {
      reviewThreads(first:100,after:$after) {
        nodes {isResolved} pageInfo {hasNextPage endCursor}
      }
    }}
  }`;
  let cursor = null;
  let unresolved = 0;
  for (let page = 0; page < 25; page++) {
    const graph = await github.graphql(query, {owner: repo.owner, name: repo.repo, number, after: cursor});
    const collection = graph.repository?.pullRequest?.reviewThreads;
    if (!collection) throw new Error('Review threads unavailable');
    unresolved += collection.nodes.filter(t => !t.isResolved).length;
    if (!collection.pageInfo.hasNextPage) break;
    if (page === 24) throw new Error('Review thread pagination limit exceeded');
    cursor = collection.pageInfo.endCursor;
  }
  const value = {
    owner: repo.owner, repository: `${repo.owner}/${repo.repo}`,
    pr: {number, head_ref: pr.head.ref, head_sha: pr.head.sha,
      head_repo: pr.head.repo?.full_name, base_ref: pr.base.ref, state: pr.state,
      draft: pr.draft, mergeable: pr.mergeable, author: pr.user.login, body: pr.body},
    issue, issue_comments: comments, unresolved_threads: unresolved,
    reviews: reviews.map(r => ({user: r.user, state: r.state,
      commit_id: r.commit_id, submitted_at: r.submitted_at})),
    files: files.map(f => ({filename: f.filename, status: f.status})),
    checks: checks.map(c => ({id: c.id, name: c.name, head_sha: c.head_sha,
      started_at: c.started_at, status: c.status, conclusion: c.conclusion, app_slug: c.app?.slug}))
  };
  fs.writeFileSync(path.join(directory, 'merge-readiness-snapshot.json'), JSON.stringify(value));
  core.setOutput('eligible', 'true');
  return value;
};
