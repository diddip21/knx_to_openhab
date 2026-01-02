# Golden Files for Charne

Generated from: `Charne.knxproj.json`
Date: 2026-01-02 21:49:57

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
python scripts/generate_golden_files.py --project tests\Charne.knxproj.json --name Charne --force
```
