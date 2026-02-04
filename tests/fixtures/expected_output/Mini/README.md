# Golden Files for Mini

Generated from: `mini_project.json`
Date: 2026-02-04 15:22:30

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
python scripts/generate_golden_files.py --project tests/fixtures/mini_project.json --name Mini --force
```
