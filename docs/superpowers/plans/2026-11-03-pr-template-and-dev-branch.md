# PR Template and Development Branch Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Establish a reusable PR checklist and a `dev` target while keeping the installer-preflight PR focused.

**Architecture:** Create `dev` from `origin/main`, add the PR template there as a separate workflow commit, then leave the installer feature branch's four commits unchanged and use `dev` as its PR base.

**Tech Stack:** Git branches, GitHub pull-request template Markdown, GitHub API via authenticated Git push.

**Spec:** `docs/superpowers/specs/2026-11-03-pr-template-and-dev-branch-design.md`

## Global Constraints

- Do not rewrite or delete existing remote branches.
- Do not modify or merge `main` directly.
- Keep installer-preflight commits separate from the PR-template commit.
- Opening the installer PR still requires explicit approval of its complete diff and a human-authored summary.

## Review Focus

- Template contains no agent-written substitute for the human-authored summary — pin with a clearly labeled required field.
- PR instructions require issue/context, compatibility, tests/results, checklist, and truthful agent/environment disclosure — inspect all sections before commit.
- `dev` starts at current `origin/main`, not at the installer feature tip — verify ancestry and remote ref after push.
- Installer feature diff against `dev` contains no PR-template or planning files — verify with `git diff --stat dev...fix/issue-25-installer-preflight`.

---

### Task 1: Establish `dev` and add the PR template

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`
- Create: `docs/superpowers/specs/2026-11-03-pr-template-and-dev-branch-design.md`
- Create: `docs/superpowers/plans/2026-11-03-pr-template-and-dev-branch.md`

**Interfaces:**
- The template is the default PR form on `dev`; include a human-authored summary section, issue/context, behavior and compatibility, tests/results, checklist, and model/harness/version/plugins disclosure.
- `dev` starts at `origin/main` and contains the template commit; installer branch remains a separate descendant of `origin/main`.

- [ ] **Step 1: Create the PR template**

Write concise Markdown prompts with no fabricated project claims. The human-summary section must clearly state that the contributor fills it in their own words; environment disclosure must ask for model, harness/version, and plugins, or hand-authored status.

- [ ] **Step 2: Verify template structure and working diff**

Run `git diff --check` and inspect every template section for actionable prompts and absence of filled-in placeholders.

- [ ] **Step 3: Create local `dev` from `origin/main` and commit only workflow files**

Before switching, confirm the only local uncommitted work is this plan/spec. Create/switch to `dev` at `origin/main`, add the template and the two workflow docs, and commit as `docs: add pull request template`.

- [ ] **Step 4: Publish `dev` and verify it**

Push the new branch without force. Verify `origin/dev` exists, has `origin/main` as an ancestor, and includes the template commit.

- [ ] **Step 5: Return to installer branch and verify PR scope**

Switch back to `fix/issue-25-installer-preflight`; confirm it remains unchanged and the diff against `dev` contains only the installer-preflight files/commits.
