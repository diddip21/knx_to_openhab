# Source Archive Resource-Budget Follow-Up

## Intent

Avoid staging both a full decompressed source tar and its extracted files, and
bound metadata allocations that `tarfile` would otherwise materialize before
yielding members.

## Approaches Considered

- **Bounded two-pass streaming (chosen):** first parse the gzip source with `tarfile` in streaming mode through a `TarInfo` subclass that checks extended-header sizes before the standard-library parser reads their bodies, while counting all raw tar bytes; then reopen the original gzip in streaming tar mode for safe extraction. This costs one extra decompression pass, but removes the decompressed temporary file, pre-rejects oversized metadata, and leaves PAX size overrides and sparse offsets to the standard parser.
- **Keep the temporary tar and combine its size with extracted files:** simpler parser changes, but forces a stricter effective source-file budget and still consumes temporary disk proportional to the full tar.
- **Custom full tar extraction parser:** avoids `tarfile` metadata behavior, but duplicates substantial standard-library parsing and safety logic.

## Goals and Constraints

- Preserve `_EXPANDED_LIMIT` as the maximum decompressed tar stream and regular-file total.
- Use fixed-size reads and no full-stream in-memory buffer or decompressed temporary file.
- Reject PAX/global-PAX/GNU long-name/long-link extended records larger than 1 MiB before `tarfile` reads their bodies.
- Bound cumulative pending local PAX metadata to 1 MiB before recursive parsing, and cumulative global PAX metadata to 1 MiB per archive.
- Bound consecutive nested PAX/GNU long-name/long-link headers to 64 before the standard parser can exhaust Python's recursion stack.
- Limit archives to 100,000 members and 16 MiB of cumulative UTF-8 member-path bytes before retaining names or creating entries.
- Validate the gzip trailer/CRC by consuming the complete stream during preflight.
- Reopen and extract the original gzip archive only after the preflight succeeds.
- Preserve existing path/type checks, selected-commit verification, and download limits.

## Acceptance

- A PAX archive that exceeds total expansion is rejected before extraction.
- A PAX or GNU extended record above 1 MiB is rejected before `tarfile` can allocate its body.
- Consecutive local PAX headers whose combined metadata exceeds 1 MiB are rejected before recursive parsing.
- A chain of more than 64 consecutive extended headers is rejected as an invalid archive before parser recursion can exhaust the stack.
- Excess member counts or aggregate member-path bytes are rejected in preflight and extraction.
- A truncated/corrupt gzip trailer is rejected.
- Extraction succeeds at the exact total-byte limit and no decompressed temporary tar is created.
