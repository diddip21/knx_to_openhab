import json
import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

config = []


def normalize_string(text: str):
    """Remove non-alphanumeric characters and convert to lowercase (unicode)."""
    return re.sub(r"\W+", "", text.casefold())


def main():
    """Main function"""
    with open("config.json", encoding="utf8") as f:
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

    def _normalize_list(items):
        """Recursively normalizes strings within a list in-place."""
        for idx, v in enumerate(items):
            items[idx] = _normalize(v)
        return items

    def _normalize_dict(d):
        """Recursively normalizes strings within a dictionary in-place."""
        for k, v in d.items():
            d[k] = _normalize(v)
        return d

    for idef in cfg["defines"]:
        if isinstance(cfg["defines"][idef], dict):
            for xidef in cfg["defines"][idef]:
                if "suffix" in xidef:
                    if isinstance(cfg["defines"][idef][xidef], list):
                        cfg["defines"][idef][xidef] = [
                            normalize_string(element) for element in cfg["defines"][idef][xidef]
                        ]
                        # remove duplicates
                        cfg["defines"][idef][xidef] = list(set(cfg["defines"][idef][xidef]))
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
            # We use shell=True/False depending on OS, but openhab-cli is usually linux specific.
            # On Windows this will likely fail or require powershell if openhab-cli is in path.
            # We'll assume standard linux environment for openhab-cli, but wrap in generic subprocess.
            proc = subprocess.run(
                ["openhab-cli", "info"], capture_output=True, text=True, timeout=5
            )
            if proc.returncode == 0:
                output = proc.stdout
                for line in output.splitlines():
                    if "OPENHAB_CONF" in line:
                        # expected: OPENHAB_CONF     | /etc/openhab                | ...
                        parts = line.split("|")
                        if len(parts) >= 2:
                            oh_conf = parts[1].strip()
                    if line.strip().startswith("User:"):
                        # expected: User:        openhab (Active Process 3201)
                        # or:       User:        openhab
                        parts = line.split(":", 1)[1].strip().split(" ")
                        if parts:
                            oh_user = parts[0]
                    if "User Groups:" in line:
                        # expected: User Groups: openhab tty dialout audio
                        parts = line.split(":", 1)[1].strip().split(" ")
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
            web_cfg_path = Path(__file__).parent / "web_ui" / "backend" / "config.json"
            if web_cfg_path.exists():
                with open(web_cfg_path, "r", encoding="utf-8") as f:
                    web_cfg = json.load(f)
                    if "openhab_path" in web_cfg:
                        fallback_path = web_cfg["openhab_path"]
                        # If it's relative, make it absolute relative to project?
                        # Or just take as is. The user request implied searching there.
                        # Assuming it might be an absolute path or relative to known location.
                        # If it's just "openhab", it's same as default level 3.
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
    # We will assume that if oh_conf is set, we want to append the subdirectories
    # defined in config.py keys or hardcoded structure?
    # The config.json has:
    #   "items_path": "openhab/items/knx.items",
    # We should replace the leading 'openhab' (or base) with oh_conf if it's absolute.

    paths_to_update = [
        "items_path",
        "things_path",
        "sitemaps_path",
        "influx_path",
        "fenster_path",
        "transform_dir_path",
    ]

    if os.path.isabs(oh_conf):
        # We need to be careful. The keys in config.json already include the folders (things/ items/).
        # Standard OPENHAB_CONF is /etc/openhab.
        # Standard subdirs are /etc/openhab/items, /etc/openhab/things.
        # The existing config values are like "openhab/items/knx.items".
        # We should strip the first component "openhab" and prepend oh_conf.
        for key in paths_to_update:
            if key in config:
                # heuristic: strip first part if it matches 'openhab' or just take the rest?
                # safer: assume the file structure inside OPENHAB_CONF is standard.
                # items -> items/, things -> things/, etc.
                # Let's rely on the subdirectory names.
                # If path contains 'items/', we map to oh_conf/items/filename
                p = Path(config[key])
                # We want to preserve the relative path structure *after* the base directory.
                # Current base is 'openhab'.
                # We can try to use relative_to('openhab') provided the string starts with openhab.
                try:
                    rel = p.relative_to("openhab")
                    config[key] = str(Path(oh_conf) / rel)
                except ValueError:
                    # Fallback logic if it doesn't start with openhab
                    # Just append it? Or warn?
                    # If it doesn't start with openhab, we might just assume it's relative to root
                    # But if we found OPENHAB_CONF, we probably want to force it there.
                    # Let's map based on parent dir name.
                    if "items" in p.parts:
                        config[key] = str(Path(oh_conf) / "items" / p.name)
                    elif "things" in p.parts:
                        config[key] = str(Path(oh_conf) / "things" / p.name)
                    elif "sitemaps" in p.parts:
                        config[key] = str(Path(oh_conf) / "sitemaps" / p.name)
                    elif "persistence" in p.parts:
                        config[key] = str(Path(oh_conf) / "persistence" / p.name)
                    elif "rules" in p.parts:
                        config[key] = str(Path(oh_conf) / "rules" / p.name)
                    elif "transform" in p.parts:
                        config[key] = str(Path(oh_conf) / "transform" / p.name)
                    else:
                        # fallback, just put it in conf root? or keep absolute?
                        # If it is already absolute, do nothing.
                        if not p.is_absolute():
                            config[key] = str(Path(oh_conf) / p.name)

    config["target_user"] = oh_user
    config["target_group"] = oh_group
    config["openhab_path"] = oh_conf


# if __name__ == "__main__":
main()
config["special_char_map"] = {
    ord("Ä"): "Ae",
    ord("Ü"): "Ue",
    ord("Ö"): "Oe",
    ord("ä"): "ae",
    ord("ü"): "ue",
    ord("ö"): "oe",
    ord("ß"): "ss",
    ord("é"): "e",
    ord("è"): "e",
    ord("á"): "a",
    ord("à"): "a",
}
# Mappings für Datenpunkttypen
datapoint_mappings = config["datapoint_mappings"]
