#!/usr/bin/env python3
"""Setup test environment for UI tests."""
import json
import sys
from pathlib import Path


def main():
    """Disable auth in backend config for tests."""
    config_path = Path('web_ui/backend/config.json')
    
    if not config_path.exists():
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Disable auth for tests
    if 'auth' not in config:
        config['auth'] = {}
    config['auth']['enabled'] = False
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"✓ Auth disabled in {config_path}")


if __name__ == '__main__':
    main()
