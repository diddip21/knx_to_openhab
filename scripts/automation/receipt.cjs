'use strict';

// Receipt only: reacting grants no approval, file scope or execution rights.
async function acknowledge({github, context}) {
  const repo = {owner: context.repo.owner, repo: context.repo.repo};
  const event = context.payload;
  const comment = event.comment;
  if (context.eventName !== 'issue_comment' || event.action !== 'created' ||
      event.issue?.pull_request || !Number.isSafeInteger(comment?.id) ||
      context.actor?.toLowerCase() !== repo.owner.toLowerCase() ||
      comment.user?.login?.toLowerCase() !== repo.owner.toLowerCase() ||
      !/^\/ai(?:\s|$)/i.test((comment.body || '').trim())) return;
  const {data: live} = await github.rest.issues.getComment({...repo, comment_id: comment.id});
  if (live.user?.login?.toLowerCase() !== repo.owner.toLowerCase() ||
      live.body !== comment.body || live.updated_at !== comment.updated_at) return;
  const reactions = await github.paginate(github.rest.reactions.listForIssueComment,
    {...repo, comment_id: comment.id, per_page: 100});
  if (reactions.some(r => r.content === 'eyes' && r.user?.login === 'github-actions[bot]')) return;
  await github.rest.reactions.createForIssueComment({...repo, comment_id: comment.id, content: 'eyes'});
}

module.exports = {acknowledge};
