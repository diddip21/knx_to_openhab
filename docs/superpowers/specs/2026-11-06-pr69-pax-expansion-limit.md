# PR #69 PAX Expansion-Limit Follow-Up

## Intent

Ensure the source-archive expansion limit applies to every decompressed tar byte,
including PAX and other metadata that Python's `tarfile` reader consumes before
yielding a member.

## Chosen Design

Stream gzip decompression into a private temporary file while counting all output
bytes. Reject as soon as output exceeds `_EXPANDED_LIMIT`; only then open the
bounded uncompressed tar with `tarfile`. Keep the existing per-file accounting
and safe extraction checks. Convert malformed or truncated gzip input into the
existing `ReleasePreparationError` contract.

## Requirements

- No decompressed stream may exceed `_EXPANDED_LIMIT`, including tar headers,
  padding, PAX records, and file contents.
- Decompression must be chunked and must not materialize unbounded metadata in
  memory.
- Temporary disk usage is bounded by `_EXPANDED_LIMIT` and the temporary file is
  closed on success or failure.
- Keep the compressed download limit, path/type validation, selected-commit
  verification, and deterministic extraction behavior unchanged.
- An over-limit PAX archive must fail before `tarfile` parses its oversized
  metadata; malformed/truncated gzip archives must fail closed.

## Acceptance

- A regression archive with a small compressed size and an oversized PAX field
  fails when its decompressed tar exceeds a monkeypatched limit, even though the
  yielded regular-file sizes are within the limit.
- Existing extraction, file-size-limit, source-verification, and release tests
  pass.
