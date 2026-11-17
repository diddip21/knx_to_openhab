'use strict';

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
  const result = {pull_requests: [], omitted_prs: Math.max(0, linked.length - 5)};
  for (const pr of linked.slice(0, 5)) {
    const files = await github.paginate(github.rest.pulls.listFiles,
      {...repo, pull_number: pr.number, per_page: 100});
    let budget = 16000;
    result.pull_requests.push({number: pr.number, head_sha: pr.head.sha, base: pr.base.ref,
      title: pr.title, body: (pr.body || '').slice(0, 2500), draft: pr.draft,
      files: files.slice(0, 40).map(f => {
        const patch = (f.patch || '').slice(0, Math.max(0, budget));
        budget -= patch.length;
        return {path: f.filename, status: f.status, patch,
          patch_incomplete: !f.patch || patch.length !== f.patch.length};
      }), files_omitted: Math.max(0, files.length - 40)});
  }
  return result;
}

module.exports = {planningContext};
