# Repository Cleanup Inventory

Audit snapshot: `main` at `6242f1d` (`2026-11-02`). This inventory supports Issue #36 and records evidence for conservative cleanup decisions. Runtime behavior, configuration formats, and generated OpenHAB output are unchanged.

## Removed duplicate data

The three `influxdb.persist` files under `tests/fixtures/expected_output/{Charne,Mini,UploadJson}/` had the same Git blob ID (`e3d8eb24af0209ba14b8cb41d0fc7dd0c33f69ef`), 165 bytes each, and content SHA-256 (`1a497fec562fd54c31af6a080f1978f3450f1a060521d6bf9f3dee65c1b0ec3a`) at the audited parent. They are now represented by `tests/fixtures/expected_output/common/influxdb.persist`. Golden comparison falls back to that shared reference, while regeneration and the manual golden generator preserve a project-local file if its persistence output differs. This consolidates 330 duplicate bytes in the current tree and keeps future project-specific output testable.

## Reviewed and retained

| Content | Evidence | Decision |
| --- | --- | --- |
| `tests/fixtures/Charne.knxproj` (6,043,486 bytes) | Referenced by UI preview, upload, SSE, job lifecycle, settings, and upload-security tests. | Keep; it covers real archive parsing and upload flows. |
| `tests/Charne.knxproj.json` (713,963 bytes) | Referenced by output validation, business-logic, YAML, and completeness tests and by golden regeneration. | Keep; it is a parsed JSON project fixture, not a duplicate of the binary `.knxproj`. |
| `tests/upload.knxprojarchive.json` and `tests/fixtures/mini_project.json` | Referenced by integration, output-regression, completeness, and golden tests. | Keep; each covers a distinct input path or minimal project case. |
| `scripts/generate_golden_files.py` and `scripts/regenerate_golden.py` | The first creates a reference set from a manually verified arbitrary project; the second refreshes the fixed three-project integration suite. Both are documented in the developer and testing guides. | Keep; their scopes differ. |
| `items.template`, `things.template`, `sitemap.template` | Used as wrappers during output export; placeholders are injected into their bodies. | Keep; they are active output inputs. |
| `openhab/icons/classic/*.svg` | Explicitly unignored by `.gitignore` and tracked as UI/output assets. | Keep. No generated OpenHAB output files are tracked; only these icons are. |
| Empty `__init__.py` files in test and web packages | Each establishes a separate Python package boundary. | Keep; identical emptiness does not make the package markers interchangeable. |

At this snapshot, the binary Charne project is the only tracked file larger than 1 MiB. No additional exact duplicate file groups were found beyond the persistence fixtures and the separate empty package markers.

## Deferred `.gitignore` correction

`git ls-files -ci --exclude-standard` reports `tests/fixtures/Charne.knxproj` and `tests/Charne.knxproj.json` as tracked files that also match the `*.knxproj*` ignore rule. Both are intentionally tracked and actively used, so this does not remove them from existing checkouts. The ignore rule should be narrowed or explicit exceptions added in a follow-up. It is deferred here because active draft PR #51 also changes `.gitignore` and conflicts with the audited `main`.

## Parallel work considered

At audit time, PR #61 was open with unresolved review threads and changes concentrated in UI/i18n, tests, and screenshots. PR #60 was open with installer/release changes. Draft PR #51 was open, conflicted with current `main`, and included updater/test work plus `.gitignore`. This cleanup touches only golden fixture organization, golden generation/validation, and this inventory document; it does not modify files from those PRs. Recheck current PR state before integrating this branch.

## Follow-up

Revisit the `.gitignore` rule after PR #51 is resolved. Keep Issue #36 open until this inventory and the remaining compatibility risk are reviewed; the ignored-but-tracked fixture rule is the remaining identified repository-maintenance item.
