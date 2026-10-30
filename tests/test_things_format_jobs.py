"""Tests for Things-format selection, safe migration, and staged reports."""

import json
import queue
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from web_ui.backend import jobs as jobs_module
from web_ui.backend.jobs import JobManager
from web_ui.backend.things_format import (
    assert_no_unmanaged_bridge_definitions,
    find_unmanaged_bridge_definitions,
    inactive_content,
    plan_things_outputs,
    validate_yaml_compatibility,
)


def _run_staged_generation(tmp_path, monkeypatch, current_format, previous_format, manual=None):
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
    for relative in managed.values():
        target = openhab_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("before\n", encoding="utf-8")

    if manual:
        manual_path = openhab_root / manual[0]
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        manual_path.write_text(manual[1], encoding="utf-8")

    configuration = {
        "openhab_path": str(openhab_root),
        "things_format": current_format,
        "items_path": "openhab/items/knx.items",
        "things_path": "openhab/things/knx.things",
        "sitemaps_path": "openhab/sitemaps/knx.sitemap",
        "influx_path": "openhab/persistence/knx.persist",
        "fenster_path": "openhab/rules/fenster.rules",
        "yaml_path": "openhab/yaml/knx.yaml",
    }
    global_config = SimpleNamespace(config=configuration)
    knx_module = SimpleNamespace(
        config=configuration,
        create_building=lambda _project: {},
        get_addresses=lambda _project: [],
        put_addresses_in_building=lambda _building, _addresses, _project: [
            {"name_long": "Test House", "floors": []}
        ],
        get_gateway_ip=lambda _project: "192.168.1.20",
        is_homekit_enabled=lambda _project: False,
        is_alexa_enabled=lambda _project: False,
    )

    class FakeEtsModule:
        def main(self, configuration):
            assert manager.operation_lock.locked()
            for key in ("items_path", "sitemaps_path", "influx_path", "fenster_path"):
                target = Path(configuration[key])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("generated\n", encoding="utf-8")
            if configuration["things_format"] == "yaml":
                target = Path(configuration["yaml_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    "version: 1\nthings:\n"
                    "  knx:ip:bridge:\n"
                    "    isBridge: true\n"
                    "  knx:device:bridge:generic:\n"
                    "    bridge: knx:ip:bridge\n"
                    "    channels:\n"
                    "      light:\n"
                    "        type: switch\n"
                    "        label: Light\n"
                    "        config: {ga: '1/1/1'}\n",
                    encoding="utf-8",
                )
            else:
                target = Path(configuration["things_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    'Bridge knx:ip:bridge [ type="ROUTER" ] {\n'
                    'Type switch : light "Light" [ ga="1/1/1" ]\n}\n',
                    encoding="utf-8",
                )

    ets_module = FakeEtsModule()
    monkeypatch.setattr(
        jobs_module,
        "_reload_generator_modules",
        lambda _project_root: (global_config, ets_module, knx_module),
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
    previous_id = "previous"
    manager._jobs[previous_id] = {
        "id": previous_id,
        "deployed": True,
        "deployed_at": 1,
        "things_format": previous_format,
    }
    project_path = tmp_path / "project.json"
    project_path.write_text("{}", encoding="utf-8")
    job = {
        "id": "current",
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


def test_inactive_content_is_valid_and_has_no_active_bridge():
    assert inactive_content("dsl").startswith("//")
    assert yaml.safe_load(inactive_content("yaml")) == {"version": 1}


def test_format_staging_includes_only_the_selected_things_output():
    managed = {
        "items_path": "items/knx.items",
        "things_path": "things/knx.things",
        "sitemaps_path": "sitemaps/knx.sitemap",
        "yaml_path": "yaml/knx.yaml",
        "completeness_report.json": "completeness_report.json",
    }

    dsl_keys, dsl_deactivate = plan_things_outputs(
        {"things_format": "dsl", "things_path": "openhab/things/knx.things"},
        managed,
        previous_format="dsl",
    )
    yaml_keys, yaml_deactivate = plan_things_outputs(
        {
            "things_format": "yaml",
            "things_path": "openhab/things/knx.things",
            "yaml_path": "openhab/yaml/knx.yaml",
        },
        managed,
        previous_format="yaml",
    )

    assert "things_path" in dsl_keys and "yaml_path" not in dsl_keys
    assert "yaml_path" in yaml_keys and "things_path" not in yaml_keys
    assert dsl_deactivate is None
    assert yaml_deactivate is None


def test_last_deployed_format_defaults_legacy_jobs_to_dsl():
    manager = JobManager.__new__(JobManager)
    manager._jobs = {
        "legacy": {"id": "legacy", "deployed": True, "created": 10},
        "yaml": {
            "id": "yaml",
            "deployed": True,
            "deployed_at": 20,
            "things_format": "yaml",
        },
    }
    manager._reload_jobs = lambda: None

    assert manager.get_last_deployed_things_format() == "yaml"

    manager._jobs = {"legacy": {"id": "legacy", "deployed": True, "created": 10}}
    assert manager.get_last_deployed_things_format() == "dsl"


@pytest.mark.parametrize(
    ("current_format", "previous_format", "inactive_key"),
    [("yaml", "dsl", "things_path"), ("dsl", "yaml", "yaml_path")],
)
def test_format_migration_stages_inactive_previous_output(
    current_format, previous_format, inactive_key
):
    managed = {
        "things_path": "things/knx.things",
        "yaml_path": "yaml/knx.yaml",
        "items_path": "items/knx.items",
    }
    configuration = {
        "things_format": current_format,
        "things_path": "openhab/things/knx.things",
        "yaml_path": "openhab/yaml/knx.yaml",
    }

    output_keys, inactive = plan_things_outputs(
        configuration, managed, previous_format=previous_format
    )

    assert inactive == inactive_key
    assert inactive_key not in output_keys
    assert ("yaml_path" if current_format == "yaml" else "things_path") in output_keys


def test_format_switch_rejects_unmanaged_duplicate_bridge(tmp_path):
    manual = tmp_path / "things" / "manual.things"
    manual.parent.mkdir()
    manual.write_text('Bridge knx:ip:bridge [ type="ROUTER" ]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="manual.things"):
        assert_no_unmanaged_bridge_definitions(
            str(tmp_path), {"things/knx.things", "yaml/knx.yaml"}
        )


@pytest.mark.parametrize(
    ("things_format", "active_key", "inactive_key"),
    [("dsl", "things_path", "yaml_path"), ("yaml", "yaml_path", "things_path")],
)
def test_job_stages_only_the_selected_things_format(
    tmp_path, monkeypatch, things_format, active_key, inactive_key
):
    manager, job, _root, managed = _run_staged_generation(
        tmp_path, monkeypatch, things_format, things_format
    )

    assert job["status"] == "completed"
    targets = {
        Path(target).relative_to(job["openhab_root"]).as_posix()
        for target in job["stage_mapping"].values()
    }
    assert managed[active_key] in targets
    assert managed[inactive_key] not in targets
    assert job["things_format"] == things_format
    manager.executor.shutdown(wait=False)


@pytest.mark.parametrize(
    ("current_format", "previous_format", "inactive_key", "marker"),
    [
        ("yaml", "dsl", "things_path", "KNX Things inactive"),
        ("dsl", "yaml", "yaml_path", "version: 1"),
    ],
)
def test_job_migration_stages_new_format_and_inactive_placeholder(
    tmp_path, monkeypatch, current_format, previous_format, inactive_key, marker
):
    manager, job, _root, managed = _run_staged_generation(
        tmp_path, monkeypatch, current_format, previous_format
    )

    assert job["status"] == "completed"
    mapping = job["stage_mapping"]
    targets = [
        Path(target).relative_to(job["openhab_root"]).as_posix() for target in mapping.values()
    ]
    assert targets[0] == managed[inactive_key]
    active_key = "yaml_path" if current_format == "yaml" else "things_path"
    assert managed[active_key] in targets
    inactive_staged = next(
        Path(staged)
        for staged, target in mapping.items()
        if Path(target).resolve() == (Path(job["openhab_root"]) / managed[inactive_key]).resolve()
    )
    assert marker in inactive_staged.read_text(encoding="utf-8")
    assert job["previous_things_format"] == previous_format
    manager.executor.shutdown(wait=False)


def test_format_switch_rejects_unmanaged_duplicate_bridge_in_job(tmp_path, monkeypatch):
    manager, job, _root, _managed = _run_staged_generation(
        tmp_path,
        monkeypatch,
        "yaml",
        "dsl",
        manual=("manual/manual.things", 'Bridge knx:ip:bridge [ type="ROUTER" ]\n'),
    )

    assert job["status"] == "failed"
    assert "manual/manual.things" in job["error"]
    assert not job.get("stage_mapping")
    manager.executor.shutdown(wait=False)


def test_format_switch_rolls_back_both_files_on_partial_deploy_failure(tmp_path, monkeypatch):
    manager, job, openhab_root, managed = _run_staged_generation(
        tmp_path, monkeypatch, "yaml", "dsl"
    )
    old_dsl = openhab_root / managed["things_path"]
    old_yaml = openhab_root / managed["yaml_path"]
    assert old_dsl.read_text(encoding="utf-8") == "before\n"
    assert old_yaml.read_text(encoding="utf-8") == "before\n"
    monkeypatch.setattr(jobs_module, "package_version", lambda _package: {"installed": "5.0.0"})

    def fail_after_deactivating_old_format(mapping, _staging_dir, _openhab_root, _managed):
        staged, target = next(iter(mapping.items()))
        Path(target).write_bytes(Path(staged).read_bytes())
        raise OSError("failure after deactivating the old Things file")

    def restore_from_backup(backup_path, root, managed_relatives):
        archive_root = Path(root).name
        with tarfile.open(backup_path, "r:gz") as archive:
            for relative in managed_relatives:
                try:
                    member = archive.extractfile(f"{archive_root}/{relative}")
                except KeyError:
                    continue
                if member is None:
                    continue
                with member:
                    (Path(root) / relative).write_bytes(member.read())

    monkeypatch.setattr(jobs_module, "deploy_staged_files", fail_after_deactivating_old_format)
    monkeypatch.setattr(jobs_module, "restore_managed_files", restore_from_backup)

    with pytest.raises(OSError, match="after deactivating"):
        manager.deploy(job["id"])

    assert old_dsl.read_text(encoding="utf-8") == "before\n"
    assert old_yaml.read_text(encoding="utf-8") == "before\n"
    assert not job.get("deployed")
    manager.executor.shutdown(wait=False)


def test_deploy_rejects_yaml_for_known_openhab_four_before_writing(tmp_path, monkeypatch):
    manager, job, openhab_root, managed = _run_staged_generation(
        tmp_path, monkeypatch, "yaml", "yaml"
    )
    live_yaml = openhab_root / managed["yaml_path"]
    original = live_yaml.read_text(encoding="utf-8")
    backups_before = len(job["backups"])
    monkeypatch.setattr(jobs_module, "package_version", lambda _package: {"installed": "4.3.6"})

    with pytest.raises(ValueError, match="5.0"):
        manager.deploy(job["id"])

    assert live_yaml.read_text(encoding="utf-8") == original
    assert len(job["backups"]) == backups_before
    assert not job.get("deployed")
    manager.executor.shutdown(wait=False)


def test_deploy_discloses_unknown_yaml_compatibility(tmp_path, monkeypatch):
    manager, job, _openhab_root, _managed = _run_staged_generation(
        tmp_path, monkeypatch, "yaml", "yaml"
    )
    monkeypatch.setattr(jobs_module, "package_version", lambda _package: {"installed": None})
    monkeypatch.setattr(
        jobs_module,
        "deploy_staged_files",
        lambda mapping, *_args: len(mapping),
    )

    success, _message = manager.deploy(job["id"])

    assert success is True
    assert "not confirmed" in job["compatibility_warning"]
    assert job["deployed"] is True
    manager.executor.shutdown(wait=False)


def test_unmanaged_yaml_bridge_is_reported_but_managed_file_is_excluded(tmp_path):
    managed = tmp_path / "yaml" / "knx.yaml"
    managed.parent.mkdir()
    managed.write_text(
        "version: 1\nthings:\n  knx:ip:bridge:\n    isBridge: true\n", encoding="utf-8"
    )
    manual = tmp_path / "misc" / "manual.yaml"
    manual.parent.mkdir()
    manual.write_text(
        "version: 1\nthings:\n  knx:ip:bridge:\n    isBridge: true\n", encoding="utf-8"
    )

    assert find_unmanaged_bridge_definitions(str(tmp_path), {"yaml/knx.yaml"}) == [
        "misc/manual.yaml"
    ]


def test_invalid_unmanaged_yaml_fails_closed_with_its_path(tmp_path):
    invalid = tmp_path / "yaml" / "manual.yaml"
    invalid.parent.mkdir()
    invalid.write_text("things: [unterminated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manual.yaml"):
        find_unmanaged_bridge_definitions(str(tmp_path), set())


def test_yaml_compatibility_rejects_openhab_four_and_warns_when_unknown():
    with pytest.raises(ValueError, match="5.0"):
        validate_yaml_compatibility("4.3.6")

    assert validate_yaml_compatibility("5.0.0") is None
    assert "not confirmed" in validate_yaml_compatibility(None)


def test_completeness_report_reads_yaml_channels(tmp_path):
    openhab = tmp_path / "openhab"
    openhab.mkdir()
    things = openhab / "knx.yaml"
    things.write_text(
        "version: 1\n"
        "things:\n"
        "  knx:ip:bridge:\n"
        "    isBridge: true\n"
        "    config: {type: ROUTER}\n"
        "  knx:device:bridge:generic:\n"
        "    bridge: knx:ip:bridge\n"
        "    channels:\n"
        "      light:\n"
        "        type: switch\n"
        "        label: Light\n"
        "        config: {ga: '1/1/1'}\n",
        encoding="utf-8",
    )
    manager = JobManager.__new__(JobManager)

    report_path = manager._write_completeness_report(
        str(things), str(openhab), things_format="yaml"
    )

    report = json.loads((openhab / "completeness_report.json").read_text(encoding="utf-8"))
    assert report_path.endswith("completeness_report.json")
    assert report["summary"]["total_things_checked"] == 1
    assert report["summary"]["missing_required"] == 0
