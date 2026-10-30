"""Adapter contract tests never launch systemd, pip, or change host policy."""

import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from installer.update_core.protocol import Paths


def adapter(runner):
    from installer.update_core.systemd import SystemdAdapter

    return SystemdAdapter(str(uuid4()), runner=runner)


def protected_paths():
    return Paths(
        Path("/opt/r"),
        Path("/opt/current"),
        Path("/etc/knx"),
        data_dir=Path("/srv/data"),
        backup_dir=Path("/srv/backups"),
    )


@pytest.mark.parametrize("mode", ["boot", "offline"])
@pytest.mark.parametrize("fault", [None, "active", "missing-after", "missing-requires"])
def test_recovery_preconditions_are_read_only(mode, fault):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[:2] == ["/usr/bin/systemctl", "show"]
        unit = "knxohui-update-recovery.service"
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                f"ActiveState={'active' if fault == 'active' else 'inactive'}\n"
                f"After={'' if fault == 'missing-after' else unit}\n"
                f"Requires={'' if fault == 'missing-requires' else unit}\n"
            ),
        )

    worker = adapter(run)
    if fault == "active" or mode == "boot" and fault is not None:
        with pytest.raises(ValueError):
            worker.verify_recovery_preconditions(mode)
    else:
        worker.verify_recovery_preconditions(mode)
        assert len(calls) == 3


@pytest.mark.parametrize("stage", ["metadata", "download", "extract", "dependencies", "migrate"])
def test_fixed_argv_and_sandbox(stage):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, stdout="ActiveState=inactive\nControlGroup=\n", stderr=""
        )

    worker = adapter(run)
    paths = Paths(
        Path("/opt/knx/releases"),
        Path("/opt/knx/current"),
        Path("/srv/custom config"),
        data_dir=Path("/srv/data"),
        backup_dir=Path("/srv/backups"),
    )
    worker.run_child(stage, paths, Path("/run/knx/work"), Path("/opt/knx/releases/1.2.3"))
    argv, options = calls[0]
    assert argv[0] == "/usr/bin/systemd-run"
    assert "--wait" in argv and "--pipe" not in argv
    properties = {arg.removeprefix("--property=") for arg in argv if arg.startswith("--property=")}
    for value in (
        "User=knxohupdate",
        "Group=knxohupdate",
        "SupplementaryGroups=",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        "CapabilityBoundingSet=",
        "KillMode=control-group",
        "PrivateDevices=yes",
        "UMask=0077",
    ):
        assert value in properties
    assert (
        f"PrivateNetwork={'no' if stage in ('metadata', 'download', 'dependencies') else 'yes'}"
        in properties
    )
    hidden = next(p for p in properties if p.startswith("InaccessiblePaths="))
    assert "/srv/custom config" in hidden and "/srv/data" in hidden and "/srv/backups" in hidden
    assert "/usr/local/libexec/knx_to_openhab/update_prepare.py" in argv
    writable = next(p for p in properties if p.startswith("ReadWritePaths="))
    assert '"/run/knx/work/output"' in writable
    assert ('"/opt/knx/releases/1.2.3"' in writable) == (stage in ("extract", "dependencies"))
    assert argv[argv.index("--") + 1 :][:2] == ["/usr/bin/python3", "-I"]
    assert not options.get("shell", False)
    assert "sudo" not in argv and "/bin/sh" not in argv
    assert options["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert any(a == "--property=RuntimeMaxSec=900" for a in argv) == (stage == "dependencies")
    assert calls[1][0][:3] == ["/usr/bin/systemctl", "stop", "--"]
    assert calls[2][0][1] == "show"


@pytest.mark.parametrize("failure", ["unsupported", "timeout", "fork"])
def test_failure_always_stops_descendants_and_confirms_dead(failure):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "systemd-run" in argv[0]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(argv, 1)
            if failure == "unsupported":
                raise subprocess.CalledProcessError(1, argv, stderr="Unknown property")
        state = (
            "ActiveState=active\nControlGroup=/child\n"
            if failure == "fork"
            else "ActiveState=inactive\nControlGroup=\n"
        )
        return subprocess.CompletedProcess(argv, 0, stdout=state, stderr="")

    worker = adapter(run)
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        worker.run_child(
            "metadata",
            protected_paths(),
            Path("/run/work"),
            None,
        )
    assert any(a[1] == "stop" for a in calls)


def test_invalid_stage_and_path_do_not_launch():
    calls = []
    worker = adapter(lambda *a, **k: calls.append(a))
    paths = protected_paths()
    for stage, workspace in (("sh", Path("/run/work")), ("metadata", Path("/run/a\nb"))):
        with pytest.raises(ValueError):
            worker.run_child(stage, paths, workspace, None)
    assert not calls


@pytest.mark.parametrize("syntax", ["${LANG}", "${NAME}", "$$"])
@pytest.mark.parametrize(
    "field",
    ["releases", "current", "config_dir", "data_dir", "backup_dir", "workspace", "candidate"],
)
def test_dollar_paths_rejected_before_any_runner_call(monkeypatch, syntax, field):
    monkeypatch.delenv("NAME", raising=False)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ActiveState=inactive\nControlGroup=\n")

    worker = adapter(run)
    paths = protected_paths()
    workspace = Path("/run/work")
    if field not in ("workspace", "candidate"):
        paths = replace(paths, **{field: getattr(paths, field) / syntax})
    candidate = paths.releases / "1.2.3"
    if field == "workspace":
        workspace /= syntax
    elif field == "candidate":
        candidate = paths.releases / syntax
    with pytest.raises(ValueError, match="Unsafe sandbox path"):
        worker.run_child("dependencies", paths, workspace, candidate)
    assert calls == []


def test_spaces_preserved_in_property_and_command_paths():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ActiveState=inactive\nControlGroup=\n")

    adapter(run).run_child(
        "dependencies", protected_paths(), Path("/run/work space"), Path("/opt/r/candidate space")
    )
    argv = calls[0]
    assert argv[argv.index("--workspace") + 1] == "/run/work space"
    assert argv[argv.index("--candidate") + 1] == "/opt/r/candidate space"
    assert ('--property=ReadWritePaths="/run/work space/output" "/opt/r/candidate space"') in argv


def test_missing_external_paths_fail_closed_before_launch():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ActiveState=inactive\nControlGroup=\n")

    worker = adapter(run)
    with pytest.raises(ValueError):
        worker.run_child(
            "metadata",
            Paths(Path("/opt/r"), Path("/opt/current"), Path("/etc/knx")),
            Path("/run/work"),
            None,
        )
    assert not calls


def test_dependencies_fixed_final_path_venv_and_no_root(monkeypatch, tmp_path):
    from installer import update_prepare

    calls = []
    (tmp_path / "venv").mkdir()
    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(ValueError, match="unprivileged"):
        update_prepare.prepare_dependencies(tmp_path, runner=lambda *a, **k: calls.append(a))
    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345)
    # This portable test checks argv; real POSIX mode/link checks are separate.
    monkeypatch.setattr(update_prepare, "_validate_prepared_tree", lambda path: None)
    update_prepare.prepare_dependencies(tmp_path, runner=lambda *a, **k: calls.append(a))
    assert calls[0][0] == [
        "/usr/bin/python3",
        "-I",
        "-m",
        "venv",
        "--copies",
        str(tmp_path / "venv"),
    ]
    assert calls[1][0][:4] == [str(tmp_path / "venv/bin/python"), "-I", "-m", "pip"]
    assert str(tmp_path / "requirements.txt") in calls[1][0]


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX venv alias")
def test_only_known_venv_alias_removed(tmp_path):
    from installer import update_prepare

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib64").symlink_to("lib", target_is_directory=True)
    update_prepare.normalize_venv(tmp_path)
    assert not (tmp_path / "lib64").exists()
    (tmp_path / "evil").symlink_to("/etc")
    with pytest.raises(ValueError):
        update_prepare.normalize_venv(tmp_path)


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX venv alias")
def test_pip_failure_does_not_leave_known_venv_alias_blocking_safe_retry(monkeypatch, tmp_path):
    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345)

    def run(argv, **kwargs):
        if "venv" in argv:
            (tmp_path / "venv/lib").mkdir(parents=True)
            (tmp_path / "venv/lib64").symlink_to("lib")
        else:
            assert not (tmp_path / "venv/lib64").is_symlink()
            raise subprocess.CalledProcessError(1, argv)

    with pytest.raises(subprocess.CalledProcessError):
        update_prepare.prepare_dependencies(tmp_path, runner=run)


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX venv alias")
def test_dependency_alias_is_normalized_at_actual_venv_location(monkeypatch, tmp_path):
    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345)

    def run(argv, **kwargs):
        if "venv" in argv:
            (tmp_path / "venv/lib").mkdir(parents=True)
            (tmp_path / "venv/lib64").symlink_to("lib")

    update_prepare.prepare_dependencies(tmp_path, runner=run)
    assert not (tmp_path / "venv/lib64").is_symlink()


def test_capture_fixed_services():
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, stdout="ActiveState=active\nUnitFileState=enabled\n"
        )

    state = adapter(run).capture_services()
    assert set(state.active) == {
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
    }
    assert all(state.active.values()) and all(state.enabled.values())


@pytest.mark.parametrize("fault", ["stop", "show", "missing"])
def test_teardown_fault_never_marks_output_safe(fault):
    def run(argv, **kwargs):
        if (fault == "stop" and argv[1] == "stop") or (fault == "show" and argv[1] == "show"):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout="" if fault == "missing" else "ActiveState=inactive\nControlGroup=\n"
        )

    worker = adapter(run)
    with pytest.raises((ValueError, subprocess.SubprocessError)):
        worker.run_child(
            "metadata",
            protected_paths(),
            Path("/run/work"),
            None,
        )
    assert "metadata" not in worker.stopped


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX venv aliases")
def test_non_venv_lib64_alias_is_not_normalized(monkeypatch, tmp_path):
    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345)
    (tmp_path / "venv").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib64").symlink_to("lib")
    with pytest.raises(ValueError):
        update_prepare.prepare_dependencies(tmp_path, runner=lambda *a, **k: None)


def test_migration_only_receives_copied_config_and_has_fixed_environment(monkeypatch, tmp_path):
    import json

    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345, raising=False)
    (tmp_path / "input.json").write_text(json.dumps({}))
    calls = []
    monkeypatch.setattr(update_prepare.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    candidate = tmp_path / "candidate"
    update_prepare.run_stage("migrate", tmp_path, candidate)
    assert calls[0][0][0] == [
        "/usr/bin/python3",
        "-I",
        str(candidate / "installer/config_migrations.py"),
        "--migrate-copy",
        str(tmp_path / "config-input.json"),
        "--output",
        str(tmp_path / "output/config.json"),
    ]
    assert set(calls[0][1]["env"]) == {"PATH", "LANG", "HOME"}


def test_stop_all_units_including_never_started_and_clear_stale_proof():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "stop":
            raise subprocess.CalledProcessError(5, argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout="LoadState=not-found\nActiveState=inactive\nControlGroup=\n"
        )

    worker = adapter(run)
    worker.stop_children(worker.request_id)
    assert worker.stopped == {"metadata", "download", "extract", "dependencies", "migrate"}
    assert len(calls) == 10
    worker.runner = lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 1))
    with pytest.raises(ValueError):
        worker.stop_children(worker.request_id)
    assert worker.stopped == set()


@pytest.mark.skipif(__import__("os").name != "posix", reason="real POSIX venv")
def test_real_final_path_venv_scripts_without_root_pip(monkeypatch):
    import os
    import tempfile

    from installer import update_prepare

    if os.geteuid() != 0:
        pytest.skip("isolated root fixture demotes actual venv creation")
    with tempfile.TemporaryDirectory(prefix="knxoh-final-venv-") as directory:
        candidate = Path(directory)
        os.chown(candidate, 65534, 65534)
        monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 65534)

        def run(argv, **options):
            if "venv" in argv:
                # ensurepip runs only as nobody inside this disposable venv.
                return subprocess.run(argv, **options, user=65534, group=65534, extra_groups=[])
            assert argv[1:5] == ["-I", "-m", "pip", "--isolated"]
            return subprocess.CompletedProcess(argv, 0)

        update_prepare.prepare_dependencies(candidate, runner=run)
        venv = candidate / "venv"
        assert not (candidate / ".venv").exists()
        assert not (venv / "bin/python").is_symlink()
        assert not (venv / "lib64").is_symlink()
        shebang = (venv / "bin/pip").read_text().splitlines()[0]
        assert shebang == f"#!{venv}/bin/python3"


@pytest.mark.parametrize("channel", ["stable", "prerelease", "invalid"])
def test_metadata_fixed_endpoints_and_invalid_channel(monkeypatch, tmp_path, channel):
    import json

    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345, raising=False)
    (tmp_path / "input.json").write_text(json.dumps({"channel": channel}))
    (tmp_path / "output").mkdir()
    calls = []

    def download(url, limit):
        calls.append(url)
        return b"{}" if channel == "stable" else b"[]"

    monkeypatch.setattr(update_prepare, "download", download)
    if channel == "invalid":
        with pytest.raises(ValueError):
            update_prepare.run_stage("metadata", tmp_path, None)
        assert not calls
    else:
        update_prepare.run_stage("metadata", tmp_path, None)
        base = "https://api.github.com/repos/diddip21/knx_to_openhab/releases"
        assert calls == [base + ("/latest" if channel == "stable" else "?per_page=100&page=1")]
        assert (tmp_path / "output/metadata.json").is_file()
