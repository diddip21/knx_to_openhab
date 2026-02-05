# Golden Files for UploadJson

Generated from: `upload.knxprojarchive.json`
Date: 2026-02-04 14:41:24

## Files
- knx.items
- knx.things
- knx.sitemap
- influxdb.persist

## Usage
These files serve as reference outputs for regression testing.
Tests in `test_output_validation.py` compare newly generated files against these golden files.

## Updating
To regenerate these golden files after verified changes:
```bash
python scripts/generate_golden_files.py --project tests/upload.knxprojarchive.json --name UploadJson --force
```
