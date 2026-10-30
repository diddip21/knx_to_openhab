"""Tests for persisting the ETS gateway source used by live reset."""

import importlib
import json
import queue
from pathlib import Path
from types import SimpleNamespace

import pytest

from web_ui.backend import jobs as jobs_module
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
