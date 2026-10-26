"""Tests for the password-free project structure preview."""

import os
import stat
from types import SimpleNamespace

import pytest

from web_ui.backend.project_preview import build_project_preview


def test_build_project_preview_uses_preparsed_project_data():
    project = {"project": "data"}
    building = {"id": "building"}
    addresses = [
        {"Group name": "Light", "Address": "1/2/3", "Floor": "Ground", "Room": "Hall"},
        {"Group name": "Unassigned", "Address": "1/2/4", "Floor": "", "Room": ""},
    ]
    house = [
        {
            "name_long": "Demo home",
            "Description": "Home",
            "floors": [
                {
                    "Description": "Ground floor",
                    "rooms": [
                        {
                            "Description": "Hall",
                            "Addresses": [{"Group name": "Light", "Address": "1/2/3"}],
                            "devices": [{"name": "Switch"}],
                        }
                    ],
                }
            ],
        }
    ]
    knx_module = SimpleNamespace(
        create_building=lambda _: pytest.fail("prepared building should be reused"),
        get_addresses=lambda _: pytest.fail("prepared addresses should be reused"),
        put_addresses_in_building=lambda *_: pytest.fail("prepared house should be reused"),
        get_gateway_ip=lambda _: "192.168.1.5",
        is_homekit_enabled=lambda _: True,
        is_alexa_enabled=lambda _: False,
    )

    preview = build_project_preview(
        project,
        knx_module,
        parsed=(building, addresses, house),
    )

    assert preview["metadata"] == {
        "project_name": "Demo home",
        "gateway_ip": "192.168.1.5",
        "homekit_enabled": True,
        "alexa_enabled": False,
        "total_addresses": 2,
        "unknown_items": [
            {"name": "Unassigned", "address": "1/2/4", "floor": "None", "room": "None"}
        ],
    }
    assert preview["buildings"][0]["floors"][0]["rooms"][0]["device_count"] == 1


def test_build_project_preview_parses_project_when_no_data_is_prepared():
    project = {"project": "data"}
    parsed = {
        "building": {"id": "building"},
        "addresses": [],
        "house": [],
    }
    knx_module = SimpleNamespace(
        create_building=lambda _: parsed["building"],
        get_addresses=lambda _: parsed["addresses"],
        put_addresses_in_building=lambda *args: parsed["house"],
        get_gateway_ip=lambda _: "192.168.1.5",
        is_homekit_enabled=lambda _: False,
        is_alexa_enabled=lambda _: False,
    )

    preview = build_project_preview(project, knx_module)

    assert preview["metadata"]["total_addresses"] == 0
    assert preview["buildings"] == []


def test_job_preview_persists_as_private_data_outside_the_job_record(tmp_path):
    from web_ui.backend.jobs import JobManager

    config = {
        "jobs_dir": str(tmp_path / "jobs"),
        "backups_dir": str(tmp_path / "backups"),
    }
    preview = {"metadata": {"project_name": "Demo home"}, "buildings": []}
    first_manager = JobManager(config)
    second_manager = None
    try:
        first_manager.save_job_preview("job-1", preview)
        preview_path = tmp_path / "jobs" / "job-1" / "project-preview.json"
        assert stat.S_IMODE(os.stat(preview_path).st_mode) == 0o600

        second_manager = JobManager(config)
        assert second_manager.get_job_preview("job-1") == preview
        assert "preview" not in second_manager._jobs.get("job-1", {})
    finally:
        first_manager.executor.shutdown(wait=True)
        if second_manager is not None:
            second_manager.executor.shutdown(wait=True)
