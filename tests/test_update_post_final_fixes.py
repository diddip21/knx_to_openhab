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


@pytest.mark.parametrize("wrapped", [False, True])
def test_checker_does_not_misdiagnose_descriptor_exhaustion(installation, monkeypatch, wrapped):
    import errno

    from installer.update_bootstrap import check_existing_release

    _, paths, _, _ = installation

    def exhausted(*args):
        error = OSError(errno.EMFILE, "fixture descriptor exhaustion")
        if wrapped:
            raise ValueError("Linux fdinfo is required for mount-boundary validation") from error
        raise error

    monkeypatch.setattr(fs, "_tree", exhausted)
    with pytest.raises(ValueError, match="descriptor resources exhausted"):
        check_existing_release(paths, paths.current.resolve(), activating=False)


@pytest.mark.parametrize("activate", [False, True])
@pytest.mark.parametrize("hard_budget", [128, 32768])
def test_isolated_admin_checker_establishes_own_fd_budget(
    installation, activate, hard_budget
):
    import resource
    import shutil

    from installer.update_core.state import LifecycleLock

    updater, paths, _, _ = installation
    old = paths.current.resolve()
    target = old
    if activate:
        target = paths.releases / "0.9.0"
        target.mkdir()
        (target / "VERSION").write_text("0.9.0\n")
    # Valid retained copy-like environment, well within the 20,000-entry contract
    # but larger than the checker subprocess's inherited soft limit.
    tree = target / "venv/lib/python3.12/site-packages"
    tree.mkdir(parents=True)
    for index in range(256):
        (tree / f"module{index}.py").write_text("# immutable dependency\n")
    source = Path(__file__).resolve().parents[1] / "installer"
    verified = paths.config_dir.parent / "verified/installer"
    verified.mkdir(parents=True)
    for name in ("update_bootstrap.py", "bootstrap_activation.py"):
        shutil.copyfile(source / name, verified / name)
    shutil.copytree(source / "update_core", verified / "update_core",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    contract = paths.config_dir / "paths.env"
    values = (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir)
    keys = ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR")
    contract.write_text("".join(f'{key}="{path}"\n' for key, path in zip(keys, values)))
    bootstrap = verified / "update_bootstrap.py"
    bootstrap.write_text(bootstrap.read_text().replace(
        'PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")',
        f"PATHS_FILE = Path({str(contract)!r})",
    ))
    state = verified / "update_core/state.py"
    state.write_text(state.read_text().replace(
        'Path("/run/lock/knxohui-lifecycle.lock")', f"Path({str(updater.lock_path)!r})",
    ))
    arguments = ["/usr/bin/python3", "-I", str(bootstrap), "--action", "check-release"]
    for key, value in zip(("--base", "--config-dir", "--data-dir", "--backup-dir"), values):
        arguments.extend((key, str(value)))
    arguments.extend(("--paths-file", str(contract), "--", str(target), str(int(activate))))
    before = (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())

    def low_limits():
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard_budget))

    with LifecycleLock(updater.lock_path).acquire() as fd:
        result = subprocess.run(
            arguments, pass_fds=(fd,), env={"KNXOH_LIFECYCLE_FD": str(fd)},
            capture_output=True, text=True, preexec_fn=low_limits, timeout=20,
        )
    if hard_budget >= 32768:
        assert result.returncode == 0 and not result.stderr, result.stderr
    else:
        assert result.returncode == 2, result.stderr
        assert "descriptor budget" in result.stderr and "32768" in result.stderr
        assert "cannot convert" not in result.stderr and "new verified release" not in result.stderr
    assert before == (os.readlink(paths.current), (paths.config_dir / "config.json").read_bytes())
