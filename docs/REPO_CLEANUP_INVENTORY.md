# Repository Cleanup Inventory

Historical snapshot for Issue #36 on `main`. For the current `dev` inventory and review decisions, see [AUDIT_dev.md](AUDIT_dev.md). The PR/Issue status statements below describe the original snapshot date and must not be read as current status.

Audit snapshot: `main` at `edf28d4` (`2026-11-03`), after PR #62. This inventory supports Issue #36 and records evidence for conservative cleanup decisions. Runtime behavior, configuration formats, and generated OpenHAB output are unchanged.

## Removed duplicate data

At parent `6242f1d`, the three `influxdb.persist` files under `tests/fixtures/expected_output/{Charne,Mini,UploadJson}/` had the same Git blob ID (`e3d8eb24af0209ba14b8cb41d0fc7dd0c33f69ef`), 165 bytes each, and content SHA-256 (`1a497fec562fd54c31af6a080f1978f3450f1a060521d6bf9f3dee65c1b0ec3a`). They are now represented by `tests/fixtures/expected_output/common/influxdb.persist`. Golden comparison falls back to that shared reference, while regeneration and the manual golden generator preserve a project-local file if its persistence output differs. This consolidates 330 duplicate bytes in the current tree and keeps future project-specific output testable.

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

At this snapshot, the binary Charne project is the only tracked file larger than 1 MiB. A fresh exact-content scan after PR #62 found no remaining duplicate groups other than the empty package marker files.

## `.gitignore` correction

Before this change, `git ls-files -ci --exclude-standard` reported `tests/fixtures/Charne.knxproj` and `tests/Charne.knxproj.json`. Both are intentionally tracked and actively used. The broad `*.knxproj*` rule remains to avoid accidentally adding user ETS projects; explicit exceptions now preserve these two fixtures, as well as the existing `tests/upload.knxprojarchive.json` fixture.

## Parallel work considered

PR #61 is closed. PR #60 remains an independent installer/release workstream; this cleanup changes only `.gitignore` and this inventory and does not alter installer or release behavior.

## Follow-up

After the exceptions, `git ls-files -ci --exclude-standard` returns no paths. The re-audit found no additional exact duplicate groups beyond empty package markers, and the Charne project remains the only tracked file over 1 MiB. Keep Issue #36 open until this inventory and the remaining compatibility risk are reviewed; close it after this change is merged and the checks pass.
