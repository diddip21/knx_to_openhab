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
- Validate the gzip trailer/CRC by consuming the complete stream during preflight.
- Reopen and extract the original gzip archive only after the preflight succeeds.
- Preserve existing path/type checks, selected-commit verification, and download limits.

## Acceptance

- A PAX archive that exceeds total expansion is rejected before extraction.
- A PAX or GNU extended record above 1 MiB is rejected before `tarfile` can allocate its body.
- A truncated/corrupt gzip trailer is rejected.
- Extraction succeeds at the exact total-byte limit and no decompressed temporary tar is created.
