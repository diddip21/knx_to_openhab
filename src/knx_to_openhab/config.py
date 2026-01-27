"""Configuration module for KNX to OpenHAB converter.

This module loads and manages the configuration from config.json and detects
OpenHAB installation paths and system users.
"""

import json
import re
import logging
import subprocess
import os
from pathlib import Path
from importlib.resources import files

logger = logging.getLogger(__name__)

config = []


def normalize_string(text: str):
    """Remove non-alphanumeric characters and convert to lowercase (unicode)."""
    return re.sub(r'\W+', '', text.casefold())


def main():
    """Main function to load and initialize configuration."""
    # Locate config.json
    # Try 1: Project root (for development)
    config_path = Path(__file__).parent.parent.parent / 'config.json'
    
    # Try 2: Fallback to same directory as this file (for installed package)
    if not config_path.exists():
        config_path = Path(__file__).parent / 'config.json'
    
    # Try 3: Last resort - check in package data (for pip installations)
    if not config_path.exists():
        try:
            config_path = files('knx_to_openhab').parent / 'config.json'
        except Exception:
            logger.warning("config.json not found in expected locations")
            raise FileNotFoundError(f"config.json not found. Checked: {config_path}")
    
    with open(config_path, encoding='utf8') as f:
        cfg = json.load(f)
    
    def _normalize(v):
        if isinstance(v, dict):
            v = _normalize_dict(v)
        elif isinstance(v, list):
            v = _normalize_list(v)
        elif isinstance(v, tuple):
            v = _normalize_list(v)
        elif isinstance(v, str):
            v = normalize_string(v)
        return v
    
    def _normalize_list(l):
        """Recursively normalizes strings within a list in-place."""
        for idx, v in enumerate(l):
            l[idx] = _normalize(v)
        return l
    
    def _normalize_dict(d):
        """Recursively normalizes strings within a dictionary in-place."""
        for v in d.items():
            v = _normalize(v)
        return d
    
    for idef in cfg['defines']:
        if isinstance(cfg['defines'][idef], dict):
            for xidef in cfg['defines'][idef]:
                if 'suffix' in xidef:
                    if isinstance(cfg['defines'][idef][xidef], list):
                        cfg['defines'][idef][xidef] = [
                            normalize_string(element) for element in cfg['defines'][idef][xidef]
                        ]
                        # remove duplicates
                        cfg['defines'][idef][xidef] = list(set(cfg['defines'][idef][xidef]))
    
    global config
    config = cfg
    
    # helper for openhab detection
    def get_openhab_conf():
        """
        Detects OPENHAB_CONF, User, and Group.
        Priority:
        1. openhab-cli info
        2. web_ui/backend/config.json
        3. Default (local 'openhab' dir, current user)
        """
        oh_conf = None
        oh_user = None
        oh_group = None

        # 1. Try openhab-cli
        try:
            proc = subprocess.run(['openhab-cli', 'info'], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                output = proc.stdout
                for line in output.splitlines():
                    if 'OPENHAB_CONF' in line:
                        # expected: OPENHAB_CONF     | /etc/openhab                | ...
                        parts = line.split('|')
                        if len(parts) >= 2:
                            oh_conf = parts[1].strip()
                    if line.strip().startswith('User:'):
                        # expected: User:        openhab (Active Process 3201)
                        # or:       User:        openhab
                        parts = line.split(':', 1)[1].strip().split(' ')
                        if parts:
                            oh_user = parts[0]
                    if 'User Groups:' in line:
                        # expected: User Groups: openhab tty dialout audio
                        parts = line.split(':', 1)[1].strip().split(' ')
                        if parts:
                            oh_group = parts[0]
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            logger.debug("openhab-cli not found or failed.")

        if oh_conf:
            logger.info("Detected OPENHAB_CONF via CLI: %s", oh_conf)
            logger.info("Detected User: %s, Group: %s", oh_user, oh_group)
            return oh_conf, oh_user, oh_group

        # 2. Try web_ui config fallback
        try:
            web_cfg_path = Path(__file__).parent / 'web_ui' / 'backend' / 'config.json'
            if web_cfg_path.exists():
                with open(web_cfg_path, 'r', encoding='utf-8') as f:
                    web_cfg = json.load(f)
                    if 'openhab_path' in web_cfg:
                        fallback_path = web_cfg['openhab_path']
                        if os.path.isabs(fallback_path):
                            oh_conf = fallback_path
        except Exception as e:
            logger.warning("Failed to read web_ui config: %s", e)

        if oh_conf:
            logger.info("Detected OPENHAB_CONF via web_ui config: %s", oh_conf)
            # Default user/group if fallback found but not via CLI
            return oh_conf, "openhab", "openhab"

        # 3. Default
        logger.info("Using default local 'openhab' configuration.")
        return "openhab", None, None  # None implies current user/group

    oh_conf, oh_user, oh_group = get_openhab_conf()
    
    # Update paths in config
    paths_to_update = [
        'items_path', 'things_path', 'sitemaps_path', 'influx_path', 'fenster_path', 'transform_dir_path'
    ]
    
    if os.path.isabs(oh_conf):
        for key in paths_to_update:
            if key in config:
                original = Path(config[key])
                try:
                    rel = original.relative_to('openhab')
                    config[key] = str(Path(oh_conf) / rel)
                except ValueError:
                    # Fallback logic if it doesn't start with openhab
                    if 'items' in original.parts:
                        config[key] = str(Path(oh_conf) / 'items' / original.name)
                    elif 'things' in original.parts:
                        config[key] = str(Path(oh_conf) / 'things' / original.name)
                    elif 'sitemaps' in original.parts:
                        config[key] = str(Path(oh_conf) / 'sitemaps' / original.name)
                    elif 'persistence' in original.parts:
                        config[key] = str(Path(oh_conf) / 'persistence' / original.name)
                    elif 'rules' in original.parts:
                        config[key] = str(Path(oh_conf) / 'rules' / original.name)
                    elif 'transform' in original.parts:
                        config[key] = str(Path(oh_conf) / 'transform' / original.name)
                    else:
                        # fallback, just put it in conf root? or keep absolute?
                        if not original.is_absolute():
                            config[key] = str(Path(oh_conf) / original.name)

    config['target_user'] = oh_user
    config['target_group'] = oh_group


# Execute on import (to maintain backwards compatibility)
main()

config['special_char_map'] = {
    ord('Ä'): 'Ae',
    ord('Ü'): 'Ue',
    ord('Ö'): 'Oe',
    ord('ä'): 'ae',
    ord('ü'): 'ue',
    ord('ö'): 'oe',
    ord('ß'): 'ss',
    ord('é'): 'e',
    ord('è'): 'e',
    ord('á'): 'a',
    ord('à'): 'a'
}

# Mappings für Datenpunkttypen
datapoint_mappings = config['datapoint_mappings']
