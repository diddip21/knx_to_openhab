"""Focused post-final-review regressions; only temporary files and fake service IO."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from installer.update_core import secure_fs as fs
from tests.test_release_updater import installation  # noqa: F401


def test_first_component_repair_activates_clean_recovery_with_live_writers(
    installation, monkeypatch
):
    from installer import update_bootstrap as admin
    from installer.update_core.state import LifecycleLock
    from installer.update_core.systemd import SystemdAdapter

    updater, paths, adapter, _ = installation
    contract = paths.config_dir / "paths.env"
    contract.write_text(
        "".join(
            f'{key}="{path}"\n'
            for key, path in zip(
                ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir),
            )
        )
    )
    pair = (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())
    prior = adapter.active.copy()
    events = []
    recovery_active = False

    def reader(argv, **kwargs):
        name = argv[-1]
        assert argv[1] == "show"
        return subprocess.CompletedProcess(
            argv, 0,
            "ActiveState=" + ("active" if adapter.active[name] else "inactive")
            + "\nAfter=knxohui-update-recovery.service\n"
            + "Requires=knxohui-update-recovery.service\n",
        )

    production = SystemdAdapter("00000000-0000-0000-0000-000000000001", runner=reader)
    adapter.verify_recovery_preconditions = production.verify_recovery_preconditions

    def service(argv):
        nonlocal recovery_active
        events.append(argv[1:])
        if argv[1:] == ["start", "knxohui-update-recovery.service"]:
            assert not recovery_active
            result = updater.recover("boot")
            if result.status != "clean":
                raise subprocess.CalledProcessError(1, argv, stderr=result.error)
            recovery_active = True
        else:
            assert argv[1:] == ["daemon-reload"]

    def setup(argv, **kwargs):
        outcome = dict.fromkeys(
            ("ui_start", "ui_enable", "cleanup_start", "cleanup_enable",
             "release_was_incomplete"), False
        )
        outcome.update(
            ui_was_active=True, ui_was_enabled=True,
            cleanup_service_was_active=True, cleanup_timer_was_active=True,
            cleanup_timer_was_enabled=True, mode="repair",
            release=str(paths.current.resolve()), previous=str(paths.current.resolve()),
            snapshot_file="",
        )
        Path(kwargs["env"]["KNXOH_BOOTSTRAP_OUTCOME"]).write_text(json.dumps(outcome))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(admin, "PATHS_FILE", contract)
    monkeypatch.setattr(admin, "LifecycleLock", lambda: LifecycleLock(updater.lock_path))
    monkeypatch.setattr(admin.subprocess, "run", setup)
    monkeypatch.setattr(admin, "_run", service)
    source = Path(__file__).resolve().parents[1] / "installer"
    assert admin.execute_setup(source, paths, contract, ["--repair"]) == 0
    assert recovery_active and adapter.active == prior
    assert events == [["daemon-reload"], ["start", "knxohui-update-recovery.service"]]
    assert pair == (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())


@pytest.mark.parametrize("state", ["gate", "maintenance", "unknown-journal"])
def test_live_writer_clean_exception_rejects_unproven_state(installation, state):
    updater, paths, adapter, _ = installation
    leaf = {
        "gate": ".updater-startup-gate.json",
        "maintenance": ".updater-maintenance.json",
        "unknown-journal": ".updater-state/journal.json",
    }[state]
    path = paths.config_dir / leaf
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}")
    before = (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())
    assert updater.recover("boot").status == "blocked"
    assert not adapter.events
    assert before == (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())
