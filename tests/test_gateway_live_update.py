"""Tests for persisting the ETS gateway source used by live reset."""

import base64
import hashlib
import importlib
import json
import queue
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from web_ui.backend import jobs as jobs_module
from web_ui.backend import gateway_undo
from web_ui.backend.gateway_config import (
    read_gateway_state,
    restore_ets_gateway_file,
    update_gateway_file,
)
from web_ui.backend.jobs import JobManager


def _generate_gateway_job(tmp_path, monkeypatch, detected_ip):
    openhab_root = tmp_path / "openhab"
    openhab_root.mkdir()
    managed = {
        "items_path": "items/knx.items",
        "things_path": "things/knx.things",
        "sitemaps_path": "sitemaps/knx.sitemap",
        "influx_path": "persistence/knx.persist",
        "fenster_path": "rules/fenster.rules",
        "yaml_path": "yaml/knx.yaml",
        "completeness_report.json": "completeness_report.json",
        "unknown_report.json": "unknown_report.json",
        "partial_report.json": "partial_report.json",
    }
    configuration = {
        "openhab_path": str(openhab_root),
        "things_format": "dsl",
        "items_path": "openhab/items/knx.items",
        "things_path": "openhab/things/knx.things",
        "sitemaps_path": "openhab/sitemaps/knx.sitemap",
        "influx_path": "openhab/persistence/knx.persist",
        "fenster_path": "openhab/rules/fenster.rules",
        "yaml_path": "openhab/yaml/knx.yaml",
        "devices": {"gateway": {"ip_address": "192.168.20.45"}},
    }
    global_config = SimpleNamespace(config=configuration)
    knx_module = SimpleNamespace(
        config=configuration,
        create_building=lambda _project: {},
        get_addresses=lambda _project: [],
        put_addresses_in_building=lambda _building, _addresses, _project: [
            {"name_long": "Test House", "floors": []}
        ],
        get_gateway_ip=lambda _project: "192.168.20.45",
        detect_gateway_ip=lambda _project: detected_ip,
        is_homekit_enabled=lambda _project: False,
        is_alexa_enabled=lambda _project: False,
    )

    class FakeEtsModule:
        floors = []
        all_addresses = []
        GWIP = None
        B_HOMEKIT = False
        B_ALEXA = False
        PRJ_NAME = "Test House"

        @staticmethod
        def main(configuration):
            for key in (
                "items_path",
                "things_path",
                "sitemaps_path",
                "influx_path",
                "fenster_path",
            ):
                target = Path(configuration[key])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("generated\n", encoding="utf-8")

    monkeypatch.setattr(
        jobs_module,
        "_reload_generator_modules",
        lambda _project_root: (global_config, FakeEtsModule, knx_module),
    )
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda _config, _project_root: (str(openhab_root), managed),
    )
    monkeypatch.setattr(
        "web_ui.backend.project_preview.build_project_preview",
        lambda *_args, **_kwargs: {},
    )

    manager = JobManager(
        {
            "jobs_dir": str(tmp_path / "jobs"),
            "staging_dir": str(tmp_path / "staging"),
            "backups_dir": str(tmp_path / "backups"),
        }
    )
    manager.executor.shutdown(wait=False)
    project_path = tmp_path / "project.json"
    project_path.write_text(json.dumps({"devices": {}}), encoding="utf-8")
    job = {
        "id": "generated",
        "input": str(project_path),
        "status": "queued",
        "created": 2,
        "backups": [],
        "log": [],
    }
    manager._jobs[job["id"]] = job
    manager.queues[job["id"]] = queue.Queue()
    manager._run_job(job["id"])
    return manager, job, openhab_root, managed


@pytest.mark.parametrize("detected_ip", ["192.168.20.30", None])
def test_generation_persists_effective_override_and_detected_ets_ip(
    tmp_path, monkeypatch, detected_ip
):
    manager, job, _openhab_root, _managed = _generate_gateway_job(
        tmp_path, monkeypatch, detected_ip
    )

    assert job["gateway_ip"] == "192.168.20.45"
    assert job["detected_gateway_ip"] == detected_ip
    assert manager.get_last_deployed_gateway_source() is None
    manager.executor.shutdown(wait=False)


def test_gateway_reset_source_requires_deployment_and_detected_metadata():
    manager = JobManager.__new__(JobManager)
    manager._jobs = {
        "staged": {
            "id": "staged",
            "deployed": False,
            "detected_gateway_ip": "192.168.20.30",
            "things_format": "dsl",
            "created": 30,
        }
    }
    manager._reload_jobs = lambda: None

    assert manager.get_last_deployed_gateway_source() is None

    manager._jobs["legacy"] = {"id": "legacy", "deployed": True, "created": 40}
    assert manager.get_last_deployed_gateway_source() is None

    manager._jobs["deployed"] = {
        "id": "deployed",
        "deployed": True,
        "deployed_at": 50,
        "detected_gateway_ip": "192.168.20.30",
        "things_format": "yaml",
    }
    assert manager.get_last_deployed_gateway_source() == {
        "job_id": "deployed",
        "detected_gateway_ip": "192.168.20.30",
        "things_format": "yaml",
    }


def test_failed_deploy_does_not_replace_source_but_successful_deploy_does(tmp_path, monkeypatch):
    manager, job, openhab_root, managed = _generate_gateway_job(
        tmp_path, monkeypatch, "192.168.20.30"
    )
    config_module = SimpleNamespace(config={"openhab_path": str(openhab_root)})
    monkeypatch.setattr(importlib, "reload", lambda _module: config_module)
    assert manager.get_last_deployed_gateway_source() is None

    def fail_deploy(*_args):
        raise OSError("simulated deploy failure")

    monkeypatch.setattr(jobs_module, "deploy_staged_files", fail_deploy)
    monkeypatch.setattr(jobs_module, "restore_managed_files", lambda *_args: 0)
    with pytest.raises(OSError, match="simulated deploy failure"):
        manager.deploy(job["id"])
    assert manager.get_last_deployed_gateway_source() is None

    monkeypatch.setattr(
        jobs_module,
        "deploy_staged_files",
        lambda mapping, *_args: len(mapping),
    )
    success, _message = manager.deploy(job["id"])

    assert success is True
    assert manager.get_last_deployed_gateway_source() == {
        "job_id": job["id"],
        "detected_gateway_ip": "192.168.20.30",
        "things_format": "dsl",
    }
    manager.executor.shutdown(wait=False)


def test_update_dsl_tunnel_changes_only_gateway_connection_values():
    content = (
        'Bridge knx:ip:bridge [ type="TUNNEL", ipAddress="192.168.20.45", '
        'portNumber=3672, autoReconnectPeriod=27, localIp="10.0.0.4" ] {\n'
        '  Thing device generic [ ] { Type switch : light "Light" [ ga="1/1/1" ] }\n'
        "}\n"
    )

    updated = update_gateway_file(content, "dsl", "2001:0db8::1")

    assert 'type="TUNNEL"' in updated
    assert 'ipAddress="2001:db8::1"' in updated
    assert "portNumber=3672" in updated
    assert "autoReconnectPeriod=27" in updated
    assert 'localIp="10.0.0.4"' in updated
    assert 'Type switch : light "Light" [ ga="1/1/1" ]' in updated


def test_update_dsl_router_adds_tunnel_fields_and_preserves_other_configuration():
    content = (
        'Bridge knx:ip:bridge [ type="ROUTER", autoReconnectPeriod=60, '
        'localIp="10.0.0.4" ] { Type switch : light "Light" [ ga="1/1/1" ] }\n'
    )

    updated = update_gateway_file(content, "dsl", "192.168.20.45")

    assert 'type="TUNNEL"' in updated
    assert 'ipAddress="192.168.20.45"' in updated
    assert "portNumber=3671" in updated
    assert "autoReconnectPeriod=60" in updated
    assert 'localIp="10.0.0.4"' in updated
    assert 'Type switch : light "Light" [ ga="1/1/1" ]' in updated


def test_update_yaml_tunnel_changes_only_bridge_connection_values():
    document = {
        "version": 1,
        "things": {
            "knx:ip:bridge": {
                "isBridge": True,
                "config": {
                    "type": "TUNNEL",
                    "ipAddress": "192.168.20.45",
                    "portNumber": 3672,
                    "autoReconnectPeriod": 27,
                    "localIp": "10.0.0.4",
                },
            },
            "knx:device:bridge:generic": {
                "bridge": "knx:ip:bridge",
                "channels": {"light": {"type": "switch", "config": {"ga": "1/1/1"}}},
            },
        },
    }

    updated = yaml.safe_load(update_gateway_file(yaml.safe_dump(document), "yaml", "2001:0db8::1"))

    assert updated["things"]["knx:ip:bridge"]["config"] == {
        "type": "TUNNEL",
        "ipAddress": "2001:db8::1",
        "portNumber": 3672,
        "autoReconnectPeriod": 27,
        "localIp": "10.0.0.4",
    }
    assert (
        updated["things"]["knx:device:bridge:generic"]
        == document["things"]["knx:device:bridge:generic"]
    )


def test_update_yaml_router_adds_tunnel_fields_and_preserves_channels():
    document = {
        "version": 1,
        "things": {
            "knx:ip:bridge": {
                "isBridge": True,
                "config": {"type": "ROUTER", "autoReconnectPeriod": 60},
            },
            "knx:device:bridge:generic": {"channels": {"light": {"type": "switch"}}},
        },
    }

    updated = yaml.safe_load(update_gateway_file(yaml.safe_dump(document), "yaml", "192.168.20.45"))

    assert updated["things"]["knx:ip:bridge"]["config"] == {
        "type": "TUNNEL",
        "autoReconnectPeriod": 60,
        "ipAddress": "192.168.20.45",
        "portNumber": 3671,
    }
    assert (
        updated["things"]["knx:device:bridge:generic"]
        == document["things"]["knx:device:bridge:generic"]
    )


def test_restore_dsl_ets_gateway_ip_and_router_mode():
    tunnel = (
        'Bridge knx:ip:bridge [ type="TUNNEL", ipAddress="192.168.20.45", '
        'portNumber=3672, autoReconnectPeriod=27, localIp="10.0.0.4" ] { }\n'
    )

    restored_tunnel = restore_ets_gateway_file(tunnel, "dsl", "2001:0db8::1")
    restored_router = restore_ets_gateway_file(tunnel, "dsl", None)

    assert 'ipAddress="2001:db8::1"' in restored_tunnel
    assert "portNumber=3672" in restored_tunnel
    assert 'type="ROUTER"' in restored_router
    assert "ipAddress=" not in restored_router
    assert "portNumber=" not in restored_router
    assert "autoReconnectPeriod=60" in restored_router
    assert 'localIp="10.0.0.4"' in restored_router


def test_restore_yaml_ets_gateway_ip_and_router_mode():
    document = {
        "version": 1,
        "things": {
            "knx:ip:bridge": {
                "isBridge": True,
                "config": {
                    "type": "TUNNEL",
                    "ipAddress": "192.168.20.45",
                    "portNumber": 3672,
                    "autoReconnectPeriod": 27,
                },
            },
            "knx:device:bridge:generic": {"channels": {"light": {"type": "switch"}}},
        },
    }

    restored_tunnel = yaml.safe_load(
        restore_ets_gateway_file(yaml.safe_dump(document), "yaml", "2001:0db8::1")
    )
    restored_router = yaml.safe_load(
        restore_ets_gateway_file(yaml.safe_dump(document), "yaml", None)
    )

    assert restored_tunnel["things"]["knx:ip:bridge"]["config"]["ipAddress"] == "2001:db8::1"
    assert restored_tunnel["things"]["knx:ip:bridge"]["config"]["portNumber"] == 3672
    assert restored_router["things"]["knx:ip:bridge"]["config"] == {
        "type": "ROUTER",
        "autoReconnectPeriod": 60,
    }
    assert (
        restored_router["things"]["knx:device:bridge:generic"]
        == document["things"]["knx:device:bridge:generic"]
    )


@pytest.mark.parametrize(
    ("content", "format_name", "ip_address", "message"),
    [
        ("", "dsl", "192.168.1.1", "bridge"),
        (
            'Bridge knx:ip:bridge [ type="TUNNEL" ] {}\n'
            'Bridge knx:ip:bridge [ type="TUNNEL" ] {}\n',
            "dsl",
            "192.168.1.1",
            "(?i)multiple",
        ),
        ("version: 1\nthings: [broken\n", "yaml", "192.168.1.1", "YAML"),
        ('Bridge knx:ip:bridge [ type="ROUTER" ] {}', "dsl", "bad-ip", "IP address"),
    ],
)
def test_gateway_file_mutation_rejects_missing_ambiguous_malformed_or_invalid_inputs(
    content, format_name, ip_address, message
):
    with pytest.raises(ValueError, match=message):
        update_gateway_file(content, format_name, ip_address)


def test_yaml_mutation_rejects_duplicate_bridge_uids():
    content = (
        "version: 1\nthings:\n"
        "  knx:ip:bridge: {isBridge: true, config: {type: ROUTER}}\n"
        "  knx:ip:bridge: {isBridge: true, config: {type: ROUTER}}\n"
    )

    with pytest.raises(ValueError, match="duplicate key"):
        update_gateway_file(content, "yaml", "192.168.1.1")


def test_read_gateway_state_does_not_claim_runtime_status(tmp_path):
    root = tmp_path / "openhab"
    things = root / "things" / "knx.things"
    things.parent.mkdir(parents=True)
    things.write_text(
        'Bridge knx:ip:bridge [ type="TUNNEL", ipAddress="192.168.20.45" ] {}\n',
        encoding="utf-8",
    )
    config = {
        "openhab_path": "openhab",
        "things_path": "openhab/things/knx.things",
        "things_format": "dsl",
        "devices": {"gateway": {"ip_address": "192.168.20.45", "other": "keep"}},
    }

    state = read_gateway_state(config, str(tmp_path))

    assert state["things_format"] == "dsl"
    assert state["gateway_ip"] == "192.168.20.45"
    assert state["gateway_mode"] == "TUNNEL"
    assert state["saved_override"] == "192.168.20.45"
    assert state["reset_available"] is False
    assert "runtime_status" not in state


def _live_update_manager(monkeypatch, tmp_path, gateway_source=None, things_format="dsl"):
    from web_ui.backend import gateway_config

    manager = JobManager.__new__(JobManager)
    manager.cfg = {}
    manager.operation_lock = threading.Lock()
    manager.jobs_dir = str(tmp_path / "jobs")
    manager.backups_dir = str(tmp_path / "backups")
    manager._reload_jobs = lambda: None
    manager.get_last_deployed_gateway_source = lambda: gateway_source
    openhab_root = tmp_path / "openhab"
    managed_path = "things/knx.things" if things_format == "dsl" else "yaml/knx.yaml"
    manager._jobs = {
        "deployed": {
            "id": "deployed",
            "deployed": True,
            "deployed_at": 1,
            "things_format": things_format,
            "openhab_root": str(openhab_root),
            "active_things_path": managed_path,
            "managed_targets": ["things/knx.things", "yaml/knx.yaml"],
        }
    }

    state = {
        "config": {
            "openhab_path": "openhab",
            "things_format": things_format,
            "things_path": "openhab/things/knx.things",
            "yaml_path": "openhab/yaml/knx.yaml",
            "devices": {
                "gateway": {
                    "ip_address": "192.168.20.45",
                    "hardware_name": ["KNX IP Interface"],
                    "other_setting": "preserve-me",
                },
                "other_device": {"enabled": True},
            },
        },
        "content": (
            (
                b'Bridge knx:ip:bridge [ type="TUNNEL", ipAddress="192.168.20.45", '
                b"portNumber=3671, autoReconnectPeriod=30 ] { }\n"
            )
            if things_format == "dsl"
            else yaml.safe_dump(
                {
                    "version": 1,
                    "things": {
                        "knx:ip:bridge": {
                            "isBridge": True,
                            "config": {
                                "type": "TUNNEL",
                                "ipAddress": "192.168.20.45",
                                "portNumber": 3671,
                                "autoReconnectPeriod": 30,
                            },
                        },
                        "knx:device:bridge:generic": {
                            "channels": {"light": {"type": "switch", "config": {"ga": "1/1/1"}}}
                        },
                    },
                },
                sort_keys=False,
            ).encode("utf-8")
        ),
        "fail_write_after_change": False,
        "fail_save": False,
        "write_calls": [],
        "save_calls": [],
    }
    managed = {"things_path": "things/knx.things", "yaml_path": "yaml/knx.yaml"}
    state["managed_paths"] = managed
    read_state = {
        "things_format": things_format,
        "managed_path": "things/knx.things" if things_format == "dsl" else "yaml/knx.yaml",
        "gateway_ip": "192.168.20.45",
        "gateway_mode": "TUNNEL",
        "saved_override": "192.168.20.45",
        "reset_available": gateway_source is not None,
    }

    monkeypatch.setattr(
        jobs_module, "load_generator_config", lambda *_args: deepcopy(state["config"])
    )
    monkeypatch.setattr(jobs_module, "package_version", lambda _package: {"installed": "5.0.0"})

    def save_config(configuration, *_args):
        state["save_calls"].append(deepcopy(configuration))
        if state["fail_save"]:
            state["fail_save"] = False
            raise OSError("simulated config save failure")
        state["config"] = deepcopy(configuration)

    monkeypatch.setattr(jobs_module, "save_generator_config", save_config)
    monkeypatch.setattr(
        jobs_module,
        "configured_managed_paths",
        lambda *_args: (str(openhab_root), managed),
    )
    monkeypatch.setattr(gateway_config, "read_gateway_state", lambda *_args: dict(read_state))
    monkeypatch.setattr(gateway_config, "read_managed_file", lambda *_args: state["content"])
    monkeypatch.setattr(jobs_module, "read_managed_file", lambda *_args: state["content"])

    def write_file(_root, relative_path, content, _managed_paths):
        state["write_calls"].append((relative_path, content))
        state["content"] = bytes(content)
        if state["fail_write_after_change"]:
            state["fail_write_after_change"] = False
            raise OSError("simulated managed-file write failure")

    monkeypatch.setattr(jobs_module, "write_managed_file", write_file)
    return manager, state, read_state


@pytest.mark.parametrize("things_format", ["dsl", "yaml"])
def test_apply_updates_active_file_and_only_gateway_override(tmp_path, monkeypatch, things_format):
    manager, state, _read_state = _live_update_manager(
        monkeypatch, tmp_path, things_format=things_format
    )

    result = manager.apply_gateway_ip("2001:0db8::1")

    assert state["config"]["devices"]["gateway"] == {
        "ip_address": "2001:db8::1",
        "hardware_name": ["KNX IP Interface"],
        "other_setting": "preserve-me",
    }
    assert state["config"]["devices"]["other_device"] == {"enabled": True}
    if things_format == "dsl":
        assert b'ipAddress="2001:db8::1"' in state["content"]
    else:
        document = yaml.safe_load(state["content"])
        assert document["things"]["knx:ip:bridge"]["config"]["ipAddress"] == "2001:db8::1"
        assert document["things"]["knx:device:bridge:generic"]["channels"]["light"]["config"] == {
            "ga": "1/1/1"
        }
    assert result["gateway_ip"] == "2001:db8::1"
    assert "runtime status was not checked" in result["message"]


def test_apply_rejects_invalid_ip_without_writing(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_config = deepcopy(state["config"])
    original_content = state["content"]

    with pytest.raises(ValueError, match="IP address"):
        manager.apply_gateway_ip("192.168.20.999")

    assert state["config"] == original_config
    assert state["content"] == original_content
    assert state["save_calls"] == []
    assert state["write_calls"] == []


def test_apply_compensates_file_and_config_when_managed_write_fails(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_config = deepcopy(state["config"])
    original_content = state["content"]
    state["fail_write_after_change"] = True

    with pytest.raises(OSError, match="simulated managed-file write failure"):
        manager.apply_gateway_ip("192.168.20.99")

    assert state["config"] == original_config
    assert state["content"] == original_content
    assert len(state["save_calls"]) == 2
    assert len(state["write_calls"]) == 2


def test_apply_persists_previous_file_and_override_for_durable_undo(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    previous_content = state["content"]

    result = manager.apply_gateway_ip("192.168.20.99")

    snapshot_path = Path(manager.backups_dir) / "gateway-live-undo.json"
    assert snapshot_path.is_file(), "successful live apply must persist an undo snapshot"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert base64.b64decode(snapshot["file_content_b64"]) == previous_content
    assert snapshot["previous_gateway_override"] == "192.168.20.45"
    assert snapshot["openhab_root"] == str(tmp_path / "openhab")
    assert snapshot["managed_path"] == "things/knx.things"
    assert snapshot["things_format"] == "dsl"
    assert snapshot["post_change_sha256"] == hashlib.sha256(state["content"]).hexdigest()
    assert result["undo_available"] is True
    assert manager.get_gateway_state()["undo_available"] is True


def test_failed_live_apply_preserves_previous_undo_snapshot(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_content = state["content"]
    original_config = deepcopy(state["config"])
    manager.apply_gateway_ip("192.168.20.99")
    snapshot_path = Path(manager.backups_dir) / "gateway-live-undo.json"
    assert snapshot_path.is_file(), "successful live apply must persist an undo snapshot"
    previous_snapshot = snapshot_path.read_bytes()

    state["content"] = original_content
    state["config"] = original_config
    state["fail_write_after_change"] = True

    with pytest.raises(OSError, match="simulated managed-file write failure"):
        manager.apply_gateway_ip("192.168.20.88")

    assert state["content"] == original_content
    assert state["config"] == original_config
    assert snapshot_path.read_bytes() == previous_snapshot


def test_live_apply_does_not_change_file_when_undo_snapshot_cannot_be_saved(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_content = state["content"]
    original_config = deepcopy(state["config"])
    backup_path_blocker = tmp_path / "not-a-directory"
    backup_path_blocker.write_text("block", encoding="utf-8")
    manager.backups_dir = str(backup_path_blocker)

    with pytest.raises(OSError):
        manager.apply_gateway_ip("192.168.20.99")

    assert state["content"] == original_content
    assert state["config"] == original_config
    assert state["save_calls"] == []
    assert state["write_calls"] == []


def test_undo_restores_only_the_previous_file_and_gateway_override(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_content = state["content"]
    original_config = deepcopy(state["config"])
    manager.apply_gateway_ip("192.168.20.99")

    result = manager.undo_gateway_ip()

    assert state["content"] == original_content
    assert state["config"]["devices"]["gateway"] == original_config["devices"]["gateway"]
    assert state["config"]["devices"]["other_device"] == {"enabled": True}
    assert result["success"] is True
    assert result["saved_override"] == "192.168.20.45"
    assert result["undo_available"] is False
    assert not (Path(manager.backups_dir) / "gateway-live-undo.json").exists()


def test_undo_refuses_a_changed_managed_file_without_writing(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    manager.apply_gateway_ip("192.168.20.99")
    live_config = deepcopy(state["config"])
    writes_before_undo = list(state["write_calls"])
    state["content"] += b"// changed outside the live gateway action\n"
    changed_content = state["content"]

    with pytest.raises(ValueError, match="Undo snapshot is stale.*managed file has changed"):
        manager.undo_gateway_ip()

    assert state["content"] == changed_content
    assert state["config"] == live_config
    assert state["write_calls"] == writes_before_undo
    assert (Path(manager.backups_dir) / "gateway-live-undo.json").is_file()
    assert manager.get_gateway_state()["undo_available"] is False


def test_undo_refuses_a_changed_deployed_target_without_writing(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(
        monkeypatch, tmp_path, things_format="yaml"
    )
    manager.apply_gateway_ip("192.168.20.99")
    live_content = state["content"]
    live_config = deepcopy(state["config"])
    writes_before_undo = list(state["write_calls"])
    manager._jobs["deployed"]["active_things_path"] = "yaml/other.yaml"
    manager._jobs["deployed"]["managed_targets"].append("yaml/other.yaml")
    state["managed_paths"]["yaml_path"] = "yaml/other.yaml"

    with pytest.raises(ValueError, match="Undo snapshot is stale.*deployed target has changed"):
        manager.undo_gateway_ip()

    assert state["content"] == live_content
    assert state["config"] == live_config
    assert state["write_calls"] == writes_before_undo
    assert (Path(manager.backups_dir) / "gateway-live-undo.json").is_file()


def test_failed_undo_compensates_and_retains_snapshot(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    manager.apply_gateway_ip("192.168.20.99")
    live_content = state["content"]
    live_config = deepcopy(state["config"])
    snapshot_path = Path(manager.backups_dir) / "gateway-live-undo.json"
    snapshot_before_undo = snapshot_path.read_bytes()
    state["fail_write_after_change"] = True

    with pytest.raises(OSError, match="simulated managed-file write failure"):
        manager.undo_gateway_ip()

    assert state["content"] == live_content
    assert state["config"] == live_config
    assert snapshot_path.read_bytes() == snapshot_before_undo


def test_apply_compensates_managed_file_when_config_save_fails(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_config = deepcopy(state["config"])
    original_content = state["content"]
    state["fail_save"] = True

    with pytest.raises(OSError, match="simulated config save failure"):
        manager.apply_gateway_ip("192.168.20.99")

    assert state["config"] == original_config
    assert state["content"] == original_content
    assert len(state["save_calls"]) == 2
    assert len(state["write_calls"]) == 1


def test_apply_reports_primary_and_compensation_failures(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_save = jobs_module.save_generator_config
    write_calls = 0

    def fail_file_write(_root, _relative_path, content, _managed_paths):
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            state["content"] = bytes(content)
            raise OSError("primary file failure")
        raise OSError("file compensation failure")

    def fail_config_restore(configuration, *args):
        if len(state["save_calls"]) == 1:
            state["save_calls"].append(deepcopy(configuration))
            raise OSError("config compensation failure")
        return original_save(configuration, *args)

    monkeypatch.setattr(jobs_module, "write_managed_file", fail_file_write)
    monkeypatch.setattr(jobs_module, "save_generator_config", fail_config_restore)

    with pytest.raises(RuntimeError) as error:
        manager.apply_gateway_ip("192.168.20.99")

    message = str(error.value)
    assert "primary file failure" in message
    assert "file compensation failure" in message
    assert "config compensation failure" in message


@pytest.mark.parametrize(
    ("detected_ip", "expected_mode", "has_tunnel_ip"),
    [("2001:0db8::1", "TUNNEL", True), (None, "ROUTER", False)],
)
def test_restore_gateway_uses_deployed_ets_source_and_clears_override(
    tmp_path, monkeypatch, detected_ip, expected_mode, has_tunnel_ip
):
    source = {
        "job_id": "deployed",
        "detected_gateway_ip": detected_ip,
        "things_format": "dsl",
    }
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path, gateway_source=source)

    result = manager.restore_gateway_ip()

    gateway_config = state["config"]["devices"]["gateway"]
    assert gateway_config["ip_address"] == ""
    assert gateway_config["other_setting"] == "preserve-me"
    assert f'type="{expected_mode}"'.encode() in state["content"]
    assert (b"ipAddress=" in state["content"]) is has_tunnel_ip
    assert result["gateway_mode"] == expected_mode


def test_restore_gateway_requires_a_successfully_deployed_ets_source(tmp_path, monkeypatch):
    manager, state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    original_content = state["content"]
    original_config = deepcopy(state["config"])

    with pytest.raises(ValueError, match="deployed ETS"):
        manager.restore_gateway_ip()

    assert state["config"] == original_config
    assert state["content"] == original_content
    assert state["save_calls"] == []
    assert state["write_calls"] == []


def test_live_gateway_operation_holds_shared_operation_lock(tmp_path, monkeypatch):
    manager, _state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    from web_ui.backend import gateway_config

    real_read_state = gateway_config.read_gateway_state

    def assert_locked(config, project_root):
        assert manager.operation_lock.locked()
        return real_read_state(config, project_root)

    monkeypatch.setattr(gateway_config, "read_gateway_state", assert_locked)
    manager.apply_gateway_ip("192.168.20.99")


@pytest.mark.parametrize("blocking_operation", ["generation", "deploy"])
def test_live_update_serializes_with_job_generation_and_deploy(
    tmp_path, monkeypatch, blocking_operation
):
    manager, _state, _read_state = _live_update_manager(monkeypatch, tmp_path)
    manager.lock = threading.Lock()
    live_lock_attempted = threading.Event()

    class TrackingLock:
        def __init__(self):
            self.lock = threading.Lock()

        def acquire(self, *args, **kwargs):
            if threading.current_thread().name == "live-update":
                live_lock_attempted.set()
            return self.lock.acquire(*args, **kwargs)

        def release(self):
            return self.lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_args):
            self.release()

    manager.operation_lock = TrackingLock()
    operation_entered = threading.Event()
    release_operation = threading.Event()
    live_finished = threading.Event()

    def hold_job_operation(*_args):
        operation_entered.set()
        assert release_operation.wait(2)

    if blocking_operation == "generation":
        manager._run_job_serialized = hold_job_operation

        def job_call():
            manager._run_job("active-job")

    else:
        manager._deploy_locked = hold_job_operation

        def job_call():
            manager.deploy("active-job")

    def live_call():
        manager.apply_gateway_ip("192.168.20.99")
        live_finished.set()

    job_thread = threading.Thread(target=job_call)
    live_thread = threading.Thread(
        target=live_call,
        name="live-update",
    )
    job_thread.start()
    assert operation_entered.wait(1)
    live_thread.start()
    assert live_lock_attempted.wait(1)
    assert not live_finished.wait(0.05)

    release_operation.set()
    job_thread.join(2)
    live_thread.join(2)

    assert not job_thread.is_alive()
    assert not live_thread.is_alive()
    assert live_finished.is_set()


def test_live_apply_does_not_call_service_or_network_clients(tmp_path, monkeypatch):
    manager, _state, _read_state = _live_update_manager(monkeypatch, tmp_path)

    def unexpected_external_call(*_args, **_kwargs):
        pytest.fail("live gateway apply must not invoke external service or network clients")

    monkeypatch.setattr(jobs_module, "package_version", unexpected_external_call)
    monkeypatch.setattr(jobs_module.subprocess, "run", unexpected_external_call)

    result = manager.apply_gateway_ip("192.168.20.99")

    assert result["success"] is True


@pytest.mark.parametrize("operation", ["apply", "reset", "undo"])
@pytest.mark.parametrize("installed_version", ["4.4.0", "5.0.0", None, "unknown"])
def test_yaml_live_operations_require_known_openhab_five(
    tmp_path, monkeypatch, operation, installed_version
):
    source = {
        "job_id": "deployed",
        "detected_gateway_ip": "192.168.20.45",
        "things_format": "yaml",
    }
    gateway_source = None if operation == "apply" else source
    manager, state, _read_state = _live_update_manager(
        monkeypatch,
        tmp_path,
        gateway_source=gateway_source,
        things_format="yaml",
    )
    monkeypatch.setattr(
        jobs_module, "package_version", lambda _package: {"installed": installed_version}
    )
    if operation == "undo":
        gateway_undo.save_snapshot(
            manager._gateway_undo_path(),
            {
                "file_content_b64": base64.b64encode(b"prior file\n").decode("ascii"),
                "previous_gateway_override": "192.168.20.45",
                "openhab_root": str(tmp_path / "openhab"),
                "managed_path": "yaml/knx.yaml",
                "things_format": "yaml",
                "post_change_sha256": hashlib.sha256(state["content"]).hexdigest(),
            },
        )
    method = {
        "apply": lambda: manager.apply_gateway_ip("192.168.20.99"),
        "reset": manager.restore_gateway_ip,
        "undo": manager.undo_gateway_ip,
    }[operation]
    allow_yaml = installed_version == "5.0.0"
    original_content = state["content"]
    original_config = deepcopy(state["config"])

    if allow_yaml:
        assert method()["success"] is True
    else:
        with pytest.raises(ValueError, match="OpenHAB 5.0 or newer"):
            method()
        assert state["content"] == original_content
        assert state["config"] == original_config
        assert state["write_calls"] == []
        assert state["save_calls"] == []


def test_last_deployed_things_target_ignores_pending_and_older_jobs():
    manager = JobManager.__new__(JobManager)
    manager._jobs = {
        "old": {
            "id": "old",
            "deployed": True,
            "deployed_at": 10,
            "things_format": "dsl",
            "openhab_root": "/srv/openhab-old",
            "active_things_path": "things/old.things",
            "managed_targets": ["things/old.things"],
        },
        "staged": {
            "id": "staged",
            "deployed": False,
            "deployed_at": 30,
            "things_format": "dsl",
            "openhab_root": "/srv/openhab-staged",
            "active_things_path": "things/staged.things",
            "managed_targets": ["things/staged.things"],
        },
        "deployed": {
            "id": "deployed",
            "deployed": True,
            "deployed_at": 20,
            "things_format": "yaml",
            "openhab_root": "/srv/openhab-active",
            "active_things_path": "yaml/knx.yaml",
            "managed_targets": ["items/knx.items", "yaml/knx.yaml"],
        },
    }
    manager._reload_jobs = lambda: None

    assert manager.get_last_deployed_things_target() == {
        "job_id": "deployed",
        "openhab_root": "/srv/openhab-active",
        "managed_path": "yaml/knx.yaml",
        "things_format": "yaml",
    }


def test_last_deployed_things_target_rejects_legacy_metadata_without_managed_path(
    tmp_path, monkeypatch
):
    manager = JobManager.__new__(JobManager)
    manager.operation_lock = threading.Lock()
    manager._jobs = {
        "legacy": {
            "id": "legacy",
            "deployed": True,
            "deployed_at": 20,
            "things_format": "yaml",
            "openhab_root": "/srv/openhab",
            "active_things_path": "yaml/knx.yaml",
        }
    }
    manager._reload_jobs = lambda: None
    monkeypatch.setattr(jobs_module, "load_generator_config", lambda *_args: {})

    assert manager.get_last_deployed_things_target() is None
    with pytest.raises(ValueError, match="No usable successfully deployed KNX Things target"):
        manager.get_gateway_state()
    with pytest.raises(ValueError, match="No usable successfully deployed KNX Things target"):
        manager.apply_gateway_ip("192.168.20.99")


def test_live_apply_updates_deployed_yaml_not_pending_dsl_config(tmp_path, monkeypatch):
    deployed_root = tmp_path / "deployed-openhab"
    pending_root = tmp_path / "pending-openhab"
    deployed_yaml = deployed_root / "yaml" / "knx.yaml"
    pending_dsl = pending_root / "things" / "knx.things"
    deployed_yaml.parent.mkdir(parents=True)
    pending_dsl.parent.mkdir(parents=True)
    deployed_yaml.write_text(
        "version: 1\n"
        "things:\n"
        "  knx:ip:bridge:\n"
        "    isBridge: true\n"
        "    config:\n"
        "      type: TUNNEL\n"
        "      ipAddress: 192.168.20.45\n"
        "      portNumber: 3671\n",
        encoding="utf-8",
    )
    pending_dsl.write_text(
        'Bridge knx:ip:bridge [ type="TUNNEL", ipAddress="192.168.20.45", '
        "portNumber=3671 ] { }\n",
        encoding="utf-8",
    )
    config = {
        "openhab_path": str(pending_root),
        "things_format": "dsl",
        "things_path": str(pending_dsl),
        "yaml_path": str(pending_root / "yaml" / "knx.yaml"),
        "devices": {"gateway": {"ip_address": "192.168.20.45", "label": "keep"}},
    }
    manager = JobManager.__new__(JobManager)
    manager.cfg = {}
    manager.operation_lock = threading.Lock()
    manager.backups_dir = str(tmp_path / "backups")
    manager._jobs = {
        "deployed": {
            "id": "deployed",
            "deployed": True,
            "deployed_at": 20,
            "things_format": "yaml",
            "openhab_root": str(deployed_root),
            "active_things_path": "yaml/knx.yaml",
            "managed_targets": ["items/knx.items", "yaml/knx.yaml"],
            "detected_gateway_ip": "192.168.20.45",
        }
    }
    manager._reload_jobs = lambda: None
    saved_configs = []
    monkeypatch.setattr(jobs_module, "load_generator_config", lambda *_args: deepcopy(config))
    monkeypatch.setattr(jobs_module, "package_version", lambda _package: {"installed": "5.0.0"})
    monkeypatch.setattr(
        jobs_module,
        "save_generator_config",
        lambda updated, *_args: saved_configs.append(deepcopy(updated)),
    )

    state = manager.get_gateway_state()

    assert state["things_format"] == "yaml"
    assert state["managed_path"] == "yaml/knx.yaml"
    assert state["configured_path"] == str(deployed_yaml)

    result = manager.apply_gateway_ip("192.168.20.99")

    assert result["things_format"] == "yaml"
    assert result["managed_path"] == "yaml/knx.yaml"
    assert yaml.safe_load(deployed_yaml.read_text(encoding="utf-8"))["things"]["knx:ip:bridge"][
        "config"
    ]["ipAddress"] == "192.168.20.99"
    assert 'ipAddress="192.168.20.45"' in pending_dsl.read_text(encoding="utf-8")
    assert saved_configs[0]["devices"]["gateway"] == {
        "ip_address": "192.168.20.99",
        "label": "keep",
    }
