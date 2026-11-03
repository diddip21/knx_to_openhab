# Pull request template and development branch

## Intent

Provide a consistent PR checklist and a development target without mixing repository workflow setup into the focused installer-preflight PR.

## Scope

- Add `.github/PULL_REQUEST_TEMPLATE.md` with sections for human-written summary, issue/context, behavior and compatibility, tests/results, review checklist, and tool/agent disclosure.
- Create `origin/dev` from the current `origin/main` and place the template there in its own commit.
- Keep the installer feature branch's commits separate and prepare it to target `dev`.

## Approaches

1. Put the template and installer changes together in one PR. This is simple but mixes workflow policy with the installer feature.
2. Add the template separately to a `dev` branch based on `main`, then target the installer PR at `dev`; **chosen** to keep the feature diff focused while establishing the requested repository convention.
3. Target `main` and defer a development branch. This does not meet the requested contribution flow.

## Constraints and non-goals

- Do not rewrite or delete existing remote branches.
- Do not merge the installer PR or modify `main` directly.
- Since `dev` does not exist, initially create it at `origin/main`; the template is a separate commit on `dev`.
- Final PR publication still requires explicit approval of the full installer diff and a human-authored summary.
