# SEC-05: KNX Upload Security

## Overview

This document describes the security measures implemented to protect against malicious, corrupted, or oversized KNX project uploads.

## Security Features

### 1. File Type Validation

**Protection against:** Executable uploads, script injection, malformed files

- **Extension whitelist:** Only `.knxproj`, `.knxprojarchive`, and `.json` files are accepted
- **Magic byte validation:** File content is checked against expected file signatures
- **MIME type matching:** File extension must match actual content type

```
Allowed extensions:
- .knxproj (ZIP archive containing KNX project)
- .knxprojarchive (ZIP archive)
- .json (JSON project dump)
```

### 2. File Size Limits

**Protection against:** Disk exhaustion, denial of service

- **Maximum upload size:** 100 MB (configurable via `max_upload_size_bytes` in `config.json`)
- **Enforced at two levels:**
  1. Flask `MAX_CONTENT_LENGTH` configuration
  2. Application-level validation before processing

### 3. ZIP Bomb Protection

**Protection against:** Decompression bombs, memory exhaustion

- **Maximum entries:** 500 files per archive
- **Maximum decompressed size:** 500 MB total
- **Compression ratio check:** Individual files with >100:1 ratio are rejected
- **Pre-extraction validation:** ZIP headers are analyzed before extraction

### 4. Path Traversal Protection

**Protection against:** Writing files outside designated directories

- **ZIP entry validation:** Entries with `../` or absolute paths are rejected
- **Tar extraction safety:** All tar members are validated before extraction
- **Path normalization:** All paths are normalized and checked against allowed directories

### 5. Password Security

**Protection against:** Password leakage in logs and storage

- **No persistence:** Passwords are NOT stored in `jobs.json`
- **Memory-only storage:** Passwords exist only in memory during job processing
- **Automatic cleanup:** Passwords are cleared from memory after job completes
- **API protection:** Passwords are never included in API responses

### 6. Temporary File Management

**Protection against:** Residual sensitive data, disk space leaks

- **Safe cleanup:** All temp files are removed in `finally` blocks
- **Error logging:** Cleanup failures are logged but don't affect processing
- **UUID-based naming:** Temp files use random names to prevent collision

## Configuration

Add these settings to `web_ui/backend/config.json`:

```json
{
  "max_upload_size_bytes": 104857600,
  "security": {
    "max_zip_entries": 500,
    "max_decompressed_size_bytes": 524288000,
    "max_compression_ratio": 100
  }
}
```

## API Error Responses

When security validation fails, the API returns:

```json
{
  "error": "File type '.exe' is not supported. Allowed types: .knxproj, .knxprojarchive, .json"
}
```

Error codes:
- `INVALID_EXTENSION` - File extension not in whitelist
- `MIME_MISMATCH` - Content doesn't match extension
- `FILE_TOO_LARGE` - Exceeds size limit
- `EMPTY_FILE` - Uploaded file is empty
- `INVALID_ZIP` - Not a valid ZIP archive
- `CONTENT_UNKNOWN` - Unrecognized file format

## Testing

Run security tests:

```bash
# Unit tests for upload validation
pytest tests/test_upload_security.py -v

# UI tests with Playwright
pytest tests/ui/test_upload_security.py -v -o addopts=
```

## Implementation Details

### Key Files

| File | Purpose |
|------|---------|
| `web_ui/backend/upload_security.py` | Core validation logic |
| `web_ui/backend/app.py` | Upload endpoint with validation |
| `web_ui/backend/jobs.py` | Password handling, safe tar extraction |
| `web_ui/backend/storage.py` | Password stripping from persistence |
| `tests/test_upload_security.py` | Security unit tests |
| `tests/ui/test_upload_security.py` | Security UI tests |

### Validation Flow

```
1. Client uploads file
   ↓
2. Flask MAX_CONTENT_LENGTH check (413 if exceeded)
   ↓
3. Extension validation (400 if invalid)
   ↓
4. Magic bytes validation (400 if mismatch)
   ↓
5. ZIP bomb checks (400 if detected)
   ↓
6. Save to disk with UUID prefix
   ↓
7. Create job (password in memory only)
   ↓
8. Process job (password retrieved from memory)
   ↓
9. Clear password from memory
```
