# Repository Cleanup Inventory

Historical snapshot for Issue #36 on `main`. For the current `dev` inventory and review decisions, see [AUDIT_dev.md](AUDIT_dev.md). The PR/Issue status statements below describe the original snapshot date and must not be read as current status.

Audit snapshot: `main` at `edf28d4` (`2026-11-03`), after PR #62. This inventory supports Issue #36 and records evidence for conservative cleanup decisions. Runtime behavior, configuration formats, and generated OpenHAB output are unchanged. Local worktrees and their uncommitted contents are outside its scope.

## Current findings

- `git ls-files -ci --exclude-standard` reports no tracked files ignored by the
  current `.gitignore`.
- An exact-content scan found no duplicate files except the three empty package
  markers: `tests/__init__.py`, `web_ui/__init__.py`, and
  `web_ui/backend/__init__.py`. They define separate Python package boundaries
  and should remain.
- `tests/fixtures/Charne.knxproj` is the only tracked file larger than 1 MiB
  (6,043,486 bytes). It is used by UI upload and parsing coverage.
- Generated OpenHAB output is ignored. Tracked files under `openhab/` are the
  intentional `icons/classic/*.svg` assets.
- No tracked runtime source or test fixture was identified as safe to delete.
- Removed `pytest-dependency` from runtime requirements because no current test
  or application code uses it. Removed the unused Selenium and Pylint
  development dependencies; UI tests use Playwright and CI runs Flake8 instead.
- Removed the duplicate `coverage[toml]` development requirement because
  `pytest-cov` already installs it.
- Removed the stale `lark-parser` check from both setup verification scripts;
  no application source or requirement uses that package. The Windows verifier
  now checks the existing project virtual environment instead of requiring a
  separate global Python command.
- The UI collection hook now marks only tests under `tests/ui/`; previously it
  marked the entire collected suite as UI and caused the default core selection
  to deselect every test.

## Retained files with verified uses

| Content | Evidence | Decision |
| --- | --- | --- |
| `tests/fixtures/Charne.knxproj` | Used by UI preview, upload, job lifecycle, and security coverage. | Keep; covers real archive parsing and upload flows. |
| `tests/Charne.knxproj.json` | Used by output, business-logic, YAML, completeness, and golden-file coverage. | Keep; it is parsed project data, not a duplicate of the binary archive. |
| `tests/upload.knxprojarchive.json` and `tests/fixtures/mini_project.json` | Used by integration, output-regression, completeness, and golden tests. | Keep; they cover distinct input cases. |
| `scripts/generate_golden_files.py` and `scripts/regenerate_golden.py` | One creates a reference set for a manually verified project; the other regenerates the fixed integration suite. | Keep; their scopes differ. |
| `items.template`, `things.template`, `sitemap.template` | Read by `ets_to_openhab.py` during legacy output export. | Keep; active generator inputs. |
| `openhab/icons/classic/*.svg` | Explicitly retained by `.gitignore` and used as UI/output assets. | Keep. |

## Consolidated persistence reference

The three identical `influxdb.persist` golden files were consolidated into
`tests/fixtures/expected_output/common/influxdb.persist`. Golden comparison uses
that shared reference, while regeneration retains a project-specific file when
its output differs. This removes duplicate fixture content without preventing
future project-specific persistence output.

## Cleanup disposition

The old `docs/superpowers/` execution plans and design notes were internal
implementation records, not product or deployment documentation. They have
been removed from the maintained branch. The release builder also excludes
repository-only agent instructions and this cleanup inventory; it continues to
include the user, production, developer, and release guides.
