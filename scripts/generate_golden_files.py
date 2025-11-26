"""
Golden File Generator

This script generates reference "golden files" from a verified KNX project.
Use this when you have manually verified that a project's output is correct
and want to use it as a reference for future regression tests.

Usage:
    python scripts/generate_golden_files.py --project tests/Charne.knxproj.json --name Charne
    python scripts/generate_golden_files.py --project tests/MyProject.knxproj --name MyProject
"""
import argparse
import json
import shutil
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

import knxproject_to_openhab
import ets_to_openhab
from config import config


def generate_golden_files(project_path: Path, golden_name: str, force: bool = False):
    """
    Generate golden files from a KNX project.
    
    Args:
        project_path: Path to .knxproj or .knxproj.json file
        golden_name: Name for the golden file set (e.g., "Charne")
        force: Overwrite existing golden files if True
    """
    # Validate project file exists
    if not project_path.exists():
        print(f"[ERROR] Project file not found: {project_path}")
        return False
    
    # Create golden files directory
    golden_dir = PROJECT_ROOT / "tests" / "fixtures" / "expected_output" / golden_name
    
    if golden_dir.exists() and not force:
        print(f"[ERROR] Golden files already exist at {golden_dir}")
        print(f"        Use --force to overwrite")
        return False
    
    golden_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[*] Generating golden files for: {project_path.name}")
    print(f"[*] Output directory: {golden_dir}")
    
    # Reset module state
    ets_to_openhab.floors = []
    ets_to_openhab.all_addresses = []
    ets_to_openhab.used_addresses = []
    ets_to_openhab.equipments = {}
    ets_to_openhab.FENSTERKONTAKTE = []
    ets_to_openhab.export_to_influx = []
    
    # Load project
    print("[*] Loading project...")
    if project_path.suffix == '.json':
        with open(project_path, encoding='utf-8') as f:
            project = json.load(f)
    else:
        from xknxproject.xknxproj import XKNXProj
        knxproj = XKNXProj(path=project_path, password=None, language="de-DE")
        project = knxproj.parse()
    
    # Generate building structure
    print("[*] Generating building structure...")
    building = knxproject_to_openhab.create_building(project)
    addresses = knxproject_to_openhab.get_addresses(project)
    house = knxproject_to_openhab.put_addresses_in_building(building, addresses, project)
    
    # Set module variables
    ets_to_openhab.floors = house[0]["floors"]
    ets_to_openhab.all_addresses = addresses
    ets_to_openhab.GWIP = knxproject_to_openhab.get_gateway_ip(project)
    ets_to_openhab.B_HOMEKIT = knxproject_to_openhab.is_homekit_enabled(project)
    ets_to_openhab.B_ALEXA = knxproject_to_openhab.is_alexa_enabled(project)
    ets_to_openhab.PRJ_NAME = house[0]['name_long']
    
    # Generate OpenHAB files
    print("[*] Generating OpenHAB files...")
    items, sitemap, things = ets_to_openhab.gen_building()
    
    # Temporarily override config paths
    original_paths = {
        'items_path': config['items_path'],
        'things_path': config['things_path'],
        'sitemaps_path': config['sitemaps_path'],
        'influx_path': config['influx_path']
    }
    
    temp_dir = PROJECT_ROOT / "temp_golden_output"
    temp_dir.mkdir(exist_ok=True)
    
    config['items_path'] = str(temp_dir / "knx.items")
    config['things_path'] = str(temp_dir / "knx.things")
    config['sitemaps_path'] = str(temp_dir / "knx.sitemap")
    config['influx_path'] = str(temp_dir / "influxdb.persist")
    
    # Export files
    ets_to_openhab.export_output(items, sitemap, things)
    
    # Restore original paths
    for key, value in original_paths.items():
        config[key] = value
    
    # Copy files to golden directory
    print("[*] Copying files to golden directory...")
    files_copied = []
    for filename in ["knx.items", "knx.things", "knx.sitemap", "influxdb.persist"]:
        src = temp_dir / filename
        dst = golden_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            files_copied.append(filename)
            print(f"   [OK] {filename}")
        else:
            print(f"   [WARN] {filename} not generated")
    
    # Cleanup temp directory
    shutil.rmtree(temp_dir)
    
    # Create README for golden files
    readme_content = f"""# Golden Files for {golden_name}

Generated from: `{project_path.name}`
Date: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Files
{chr(10).join(f'- {f}' for f in files_copied)}

## Usage
These files serve as reference outputs for regression testing.
Tests in `test_output_validation.py` compare newly generated files against these golden files.

## Updating
To regenerate these golden files after verified changes:
```bash
python scripts/generate_golden_files.py --project {project_path} --name {golden_name} --force
```
"""
    
    readme_path = golden_dir / "README.md"
    readme_path.write_text(readme_content, encoding='utf-8')
    print(f"   [OK] README.md")
    
    print(f"\n[SUCCESS] Golden files generated successfully!")
    print(f"[*] Location: {golden_dir}")
    print(f"[*] Files: {len(files_copied)}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Generate golden reference files from a verified KNX project'
    )
    parser.add_argument(
        '--project',
        type=Path,
        required=True,
        help='Path to .knxproj or .knxproj.json file'
    )
    parser.add_argument(
        '--name',
        type=str,
        required=True,
        help='Name for the golden file set (e.g., "Charne", "MyProject")'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing golden files'
    )
    
    args = parser.parse_args()
    
    success = generate_golden_files(args.project, args.name, args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
