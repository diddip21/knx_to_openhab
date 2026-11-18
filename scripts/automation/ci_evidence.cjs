'use strict';

// Keep all gates on one actual CI run. Never combine check names from unrelated runs.
async function latestDispatchedRun({github, repo, branch, headSha}) {
  const repository = `${repo.owner}/${repo.repo}`;
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    ...repo, workflow_id: 'ci.yml', branch, head_sha: headSha,
    event: 'workflow_dispatch', per_page: 100
  });
  if (runs.length > 1000) throw new Error('CI evidence exceeds run history limit');
  return runs.filter(run => run.path === '.github/workflows/ci.yml' && run.name === 'CI' &&
    run.event === 'workflow_dispatch' && run.head_branch === branch &&
    run.head_sha === headSha && run.head_repository?.full_name === repository &&
    Number.isSafeInteger(run.id) && Number.isSafeInteger(run.run_attempt))
    .sort((a, b) => b.id - a.id || b.run_attempt - a.run_attempt)[0] || null;
}

async function collectCI({github, repo, branch, headSha}) {
  const selected = await latestDispatchedRun({github, repo, branch, headSha});
  if (!selected) return null;
  const {data: run} = await github.rest.actions.getWorkflowRun({...repo, run_id: selected.id});
  if (run.id !== selected.id || run.run_attempt !== selected.run_attempt ||
      run.head_sha !== headSha || run.head_branch !== branch ||
      run.head_repository?.full_name !== `${repo.owner}/${repo.repo}` ||
      run.path !== '.github/workflows/ci.yml' || run.event !== 'workflow_dispatch') {
    throw new Error('CI changed while collecting evidence; refresh the report');
  }
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRun, {
    ...repo, run_id: run.id, filter: 'latest', per_page: 100
  });
  if (jobs.length > 1000) throw new Error('CI evidence exceeds job limit');
  return {
    id: run.id, run_attempt: run.run_attempt, head_sha: run.head_sha,
    head_branch: run.head_branch, head_repo: run.head_repository.full_name,
    event: run.event, path: run.path, status: run.status, conclusion: run.conclusion,
    url: `https://github.com/${repo.owner}/${repo.repo}/actions/runs/${run.id}`,
    jobs: jobs.map(job => ({id: job.id, name: job.name, run_id: job.run_id,
      run_attempt: job.run_attempt, head_sha: job.head_sha,
      status: job.status, conclusion: job.conclusion}))
  };
}

module.exports = {latestDispatchedRun, collectCI};
