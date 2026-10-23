"""Tests for KNX gateway address selection and reprocess configuration reloads."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import knxproject_to_openhab


def _set_gateway_config(monkeypatch, ip_address=""):
    monkeypatch.setattr(
        knxproject_to_openhab,
        "config",
        {"devices": {"gateway": {"hardware_name": ["KNX IP Interface"], "ip_address": ip_address}}},
    )


def test_get_gateway_ip_uses_valid_override(monkeypatch):
    _set_gateway_config(monkeypatch, " 192.168.10.25 ")

    assert knxproject_to_openhab.get_gateway_ip({"devices": {}}) == "192.168.10.25"


def test_get_gateway_ip_accepts_ipv6_override(monkeypatch):
    _set_gateway_config(monkeypatch, "2001:0db8:0000:0000:0000:0000:0000:0001")

    assert knxproject_to_openhab.get_gateway_ip({"devices": {}}) == "2001:db8::1"


def test_get_gateway_ip_rejects_invalid_override(monkeypatch):
    _set_gateway_config(monkeypatch, "192.168.10.999")

    with pytest.raises(ValueError, match="Invalid gateway IP address configured"):
        knxproject_to_openhab.get_gateway_ip({"devices": {}})


def test_get_gateway_ip_keeps_ets_detection_when_override_is_blank(monkeypatch):
    _set_gateway_config(monkeypatch)
    project = {
        "devices": {
            "gateway": {
                "hardware_name": "KNX IP Interface Secure",
                "description": "Address 192.168.10.30",
            }
        }
    }

    assert knxproject_to_openhab.get_gateway_ip(project) == "192.168.10.30"


def test_generator_modules_bind_fresh_config_during_reprocess(tmp_path):
    """The reprocess import order must expose the newly saved IP override to generation."""
    project_root = Path(__file__).resolve().parents[1]
    config_data = json.loads((project_root / "config.json").read_text(encoding="utf-8"))
    config_data["devices"]["gateway"]["ip_address"] = "192.168.20.45"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    config_dir.mkdir()
    data_dir.mkdir()
    backup_dir.mkdir()
    (data_dir / "generator.json").write_text(json.dumps(config_data), encoding="utf-8")

    script = """
import sys
from web_ui.backend.jobs import _reload_generator_modules

project_root = sys.argv[1]
config_module, ets_module, knx_module = _reload_generator_modules(project_root)
assert ets_module.config is config_module.config
assert knx_module.config is config_module.config
assert knx_module.get_gateway_ip({"devices": {}}) == "192.168.20.45"
"""
    env = os.environ.copy()
    env.update(
        {
            "KNXOH_INSTALL_DIR": project_root.as_posix(),
            "KNXOH_CONFIG_DIR": config_dir.as_posix(),
            "KNXOH_DATA_DIR": data_dir.as_posix(),
            "KNXOH_BACKUP_DIR": backup_dir.as_posix(),
            "KNXOH_PATHS_FILE": (tmp_path / "paths.env").as_posix(),
        }
    )
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [project_root.as_posix(), env.get("PYTHONPATH")])
    )
    result = subprocess.run(
        [sys.executable, "-c", script, project_root.as_posix()],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
