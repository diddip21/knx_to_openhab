# PR #69 CI test-fixture correction

## Intent

Make the root-run core suite reliable on the current Ubuntu GitHub runner while
continuing to enforce the maintenance-lock ownership policy.

## Scope and constraints

- Update only test expectations and fixtures; do not change production code or
  weaken lock validation.
- Model systemd consistently: a `/dev/null` unit symlink is used with
  `LoadState=masked`; a loaded unit starts from a regular existing unit file.
- Lock-path tests must verify rejection while allowing either the dedicated-path
  diagnostic or the stricter untrusted-ancestor diagnostic.

## Approaches

1. **Correct test assumptions (selected):** align fixture state with the mocked
   systemd load state and accept both valid lock rejection messages. This keeps
   security behavior unchanged and makes tests independent of runner directory
   ownership details.
2. **Change the systemd installer:** explicitly replace symlink destinations.
   This changes production behavior and is unnecessary for the inconsistent
   fixture state.
3. **Pin Ubuntu 24.04:** avoid the current runner image. This hides the fragile
   test assumptions and delays compatibility with the active runner.

## Acceptance criteria

- The masked-unit tests continue to prove that `/dev/null` symlinks are
  preserved and not started.
- The loaded-unit tests exercise installation over a regular existing unit.
- Common shared lock directories remain rejected; their rejection reason may
  depend on the runner's ancestor ownership and permissions.
- Focused tests and the full root-run core suite pass; no production behavior
  changes.
