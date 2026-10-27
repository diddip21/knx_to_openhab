# Conservative Repository Cleanup — Design

## Intent

Complete Issue #36 after install/update work, using a traceable inventory rather than broad cleanup. Prior PR #37 already removed a first set of proven duplicates; this pass should remove only files with no runtime, test, documentation, CI, or external references.

## Goals

- Inventory tracked files, duplicate content, generated artifacts, imports, scripts, and test collection.
- Remove only unambiguously unused or duplicated items, one reviewed group at a time.
- Update references and document every removal; retain compatibility-relevant configuration and fixtures.

## Non-goals

- No production refactor, renaming campaign, output/config format changes, or Issue #38 work.
- No deletion based only on filename, age, or low test coverage.

## Approaches

1. **Broad cleanup sweep:** fast, but deletion risk is high in a generator with dynamic imports, templates, and deployment scripts. Rejected.
2. **Reference-driven conservative inventory (chosen):** combine Git inventory, Python imports/test collection, shell/CI/docs references, and content hashes; remove only proven candidates and retain an audit list.
3. **No removals:** safest but leaves the issue without a verifiable repository-wide review. Rejected unless inventory finds no safe candidates.

## Constraints

- Every removed path must have evidence and an accompanying focused test/CI run.
- Preserve supported configuration keys, examples, fixtures, and compatibility files.
- Run core tests/lint and `git diff --check`; report files that cannot be confidently classified as follow-up candidates.
