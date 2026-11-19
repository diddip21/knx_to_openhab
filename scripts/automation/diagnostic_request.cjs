'use strict';

function diagnosticIssue(context) {
  const owner = context.repo.owner.toLowerCase();
  if (context.actor?.toLowerCase() !== owner) throw new Error('Owner diagnostic request required');
  let value;
  if (context.eventName === 'workflow_dispatch') {
    value = context.payload.inputs?.issue_number;
  } else if (context.eventName === 'pull_request') {
    const pr = context.payload.pull_request;
    if (pr?.head?.repo?.full_name !== `${context.repo.owner}/${context.repo.repo}` ||
        pr.user?.login?.toLowerCase() !== owner) throw new Error('Same-repository owner PR required');
    const matches = [...(pr.body || '').matchAll(/^AI-Plan-Diagnostic-Issue: ([1-9][0-9]*)$/gm)];
    if (matches.length !== 1) throw new Error('Exactly one explicit diagnostic issue is required');
    value = matches[0][1];
  } else throw new Error('Unexpected diagnostic event');
  if (typeof value !== 'string' || !/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(Number(value))) {
    throw new Error('Invalid diagnostic issue number');
  }
  return Number(value);
}

module.exports = {diagnosticIssue};
