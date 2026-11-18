'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {diagnosticIssue} = require('../../scripts/automation/diagnostic_request.cjs');

function request(body = 'AI-Plan-Diagnostic-Issue: 137') {
  return {eventName:'pull_request',actor:'owner',repo:{owner:'owner',repo:'repo'},
    payload:{pull_request:{body,user:{login:'owner'},head:{repo:{full_name:'owner/repo'}}}}};
}

test('diagnostic context is explicit and generic', () => {
  assert.equal(diagnosticIssue(request()), 137);
  assert.equal(diagnosticIssue(request('AI-Plan-Diagnostic-Issue: 1234')), 1234);
  const context = request();
  context.eventName = 'workflow_dispatch';
  context.payload = {inputs:{issue_number:'42'}};
  assert.equal(diagnosticIssue(context), 42);
});

test('diagnostic rejects ambiguous, foreign or implicit requests', () => {
  for (const body of ['', 'mentions #89', 'AI-Plan-Diagnostic-Issue: 0',
    'AI-Plan-Diagnostic-Issue: 9007199254740992',
    'AI-Plan-Diagnostic-Issue: 89\nAI-Plan-Diagnostic-Issue: 137']) {
    assert.throws(() => diagnosticIssue(request(body)));
  }
  const foreign = request();
  foreign.payload.pull_request.head.repo.full_name = 'other/repo';
  assert.throws(() => diagnosticIssue(foreign));
  const nonOwner = request();
  nonOwner.actor = 'other';
  assert.throws(() => diagnosticIssue(nonOwner));
});
