"""Real setup shell + administrator parent, with only host effects faked."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("previous", ["relative", "absolute", "absent"])
def test_final_path_venv_interruption_recovers_through_real_envelope(monkeypatch, previous):
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("protected Linux root shell/FD fixture")
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths
    from installer.update_core.state import LifecycleLock

    with tempfile.TemporaryDirectory(prefix="knxoh-shell-recovery-", dir="/run") as tmp:
        root = Path(tmp)
        source = root / "verified-source"
        installer = source / "installer"
        installer.mkdir(parents=True)
        # Use actual trusted code, including nested validate and inherited FD.
        for name in (
            "__init__.py",
            "update_bootstrap.py",
            "bootstrap_activation.py",
            "config_migrations.py",
            "knxohui.service",
            "launch_web.sh",
        ):
            shutil.copyfile(ROOT / "installer" / name, installer / name)
        shutil.copytree(
            ROOT / "installer/update_core",
            installer / "update_core",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        (source / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/build_release.py", source / "scripts/build_release.py")
        (source / "VERSION").write_text("2.0.0\n")
        (source / "requirements.txt").write_bytes(b"")
        paths = Paths(
            root / "app/releases",
            root / "app/current",
            root / "config",
            root / "data",
            root / "backup",
        )
        for folder in (paths.releases, paths.config_dir, paths.data_dir, paths.backup_dir):
            folder.mkdir(parents=True)
        old = paths.releases / "1.0.0"
        if previous != "absent":
            old.mkdir()
            paths.current.symlink_to(old if previous == "absolute" else "releases/1.0.0")
        config = paths.config_dir / "config.json"
        config.write_bytes(b'{"unchanged":true}\n')
        contract = root / "paths.env"
        contract.write_text(
            "".join(
                f'{key}="{value}"\n'
                for key, value in zip(
                    ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                    (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir),
                )
            )
        )
        lock = LifecycleLock(root / "host.lock")
        monkeypatch.setattr(admin, "PATHS_FILE", contract)
        monkeypatch.setattr(admin, "LifecycleLock", lambda: lock)
        bootstrap = installer / "update_bootstrap.py"
        bootstrap.write_text(
            bootstrap.read_text().replace(
                'PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")',
                f"PATHS_FILE = Path({str(contract)!r})",
            )
        )
        state = installer / "update_core/state.py"
        state.write_text(
            state.read_text().replace(
                'Path("/run/lock/knxohui-lifecycle.lock")', f"Path({str(lock.path)!r})"
            )
        )
        tools = root / "tools"
        tools.mkdir()
        log, poison = root / "commands.jsonl", root / "partial-env-executed"
        sudo = tools / "sudo"
        sudo.write_text(
            "#!/usr/bin/python3 -I\n"
            "import json, os, shutil, signal, subprocess, sys\n"
            "from pathlib import Path\n"
            f"root = Path({str(root)!r}); log = Path({str(log)!r})\n"
            "args = sys.argv[1:]; cmd = args.pop(0)\n"
            "with log.open('a') as out: out.write(json.dumps([cmd, *args]) + '\\n')\n"
            "if cmd == 'systemctl':\n"
            f"    sys.exit(0 if {previous != 'absent'!r} and args[0] in ('is-active', 'is-enabled') else 1)\n"
            "if cmd == 'chown': sys.exit(0)  # no host accounts needed\n"
            "if cmd == 'usermod' and args == ['-a', '-G', 'openhab', 'knxohui']: sys.exit(0)\n"
            "if cmd == 'rsync':\n"
            "    shutil.copytree(args[-2].rstrip('/'), args[-1], dirs_exist_ok=True)\n"
            "    sys.exit(0)\n"
            "if cmd == 'python3' and args[:2] == ['-m', 'venv']:\n"
            "    venv = Path(args[-1]); (venv / 'bin').mkdir(parents=True)\n"
            f"    (venv / 'bin/python').write_text('#!/bin/sh\\ntouch {poison}\\nexit 99\\n')\n"
            "    (venv / 'bin/python').chmod(0o755)\n"
            "    os.kill(os.getppid(), signal.SIGKILL)  # ONLY the disposable setup Bash\n"
            "    sys.exit(137)\n"
            "if '/venv/' in cmd: raise AssertionError('partial environment invocation')\n"
            "if cmd not in ('mkdir', 'chmod', 'touch', 'mv', 'ln', 'rm'):\n"
            "    raise AssertionError('unexpected privileged effect: ' + cmd)\n"
            "for arg in args:\n"
            "    if arg.startswith('/') and not Path(arg).is_relative_to(root):\n"
            "        raise AssertionError('host path outside fixture: ' + arg)\n"
            "sys.exit(subprocess.run(['/usr/bin/' + cmd, *args], check=False).returncode)\n"
        )
        sudo.chmod(0o755)
        for name, text in (
            ("dpkg", "echo 'Status: install ok installed'\n"),
            ("getent", "exit 0\n"),
            ("id", "exit 0\n"),
        ):
            tool = tools / name
            tool.write_text("#!/bin/sh\n" + text)
            tool.chmod(0o755)
        setup = installer / "setup.sh"
        raw = (ROOT / "installer/setup.sh").read_text()
        # Only privileged command boundaries point to temporary fake binaries.
        # The real state/recovery functions, cwd, FD envelope and CLI remain intact.
        raw = raw.replace("sudo ", str(sudo) + " ")
        for name, suffix in (("dpkg", " -s"), ("getent", " group"), ("id", " -u")):
            raw = raw.replace(name + suffix, str(tools / name) + suffix)
        setup.write_text(raw)
        service_calls = []

        def fake_services(argv):
            with lock.acquire():
                service_calls.append(argv)

        monkeypatch.setattr(admin, "_run", fake_services)
        assert admin.execute_setup(installer, paths, contract, []) == -9
        failed = paths.releases / "2.0.0"
        transaction = failed / ".installer-transaction-state"
        assert transaction.exists() and (failed / "venv/bin/python").exists()
        if previous == "relative":
            lines = transaction.read_text().splitlines()
            lines[0] = "releases/1.0.0"  # persisted legacy/repair record, NOT the later outcome
            transaction.write_text("\n".join(lines) + "\n")
        monkeypatch.setenv("KNXOH_REPAIR_TARGET", str(failed))
        result = admin.execute_setup(
            installer, paths, contract, ["--repair", "--activate-existing"]
        )
        assert result == (2 if previous == "absent" else 0)
        if previous == "absent":
            assert not paths.current.exists() and not paths.current.is_symlink()
            assert service_calls == []
        else:
            assert paths.current.resolve() == old
            assert [
                "/usr/bin/systemctl",
                "start",
                "knxohui-update-recovery.service",
            ] in service_calls
        assert not failed.exists()
        assert config.read_bytes() == b'{"unchanged":true}\n'
        assert not poison.exists()
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        assert sum(cmd[:4] == ["python3", "-m", "venv", "--copies"] for cmd in commands) == 1
        assert not any("/venv/" in cmd[0] for cmd in commands)


@pytest.mark.parametrize("was_incomplete", [False, True])
def test_component_repair_activation_failure_preserves_marker_and_services(
    monkeypatch, was_incomplete
):
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("protected Linux root fixture")
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths
    from installer.update_core.state import LifecycleLock, check_start_allowed

    with tempfile.TemporaryDirectory(prefix="knxoh-repair-rollback-", dir="/run") as tmp:
        root = Path(tmp)
        paths = Paths(
            root / "app/releases",
            root / "app/current",
            root / "config",
            root / "data",
            root / "backup",
        )
        for folder in (paths.releases, paths.config_dir, paths.data_dir, paths.backup_dir):
            folder.mkdir(parents=True)
        release = paths.releases / "1.0.0"
        release.mkdir()
        paths.current.symlink_to("releases/1.0.0")
        config = paths.config_dir / "config.json"
        config.write_bytes(b'{"preserve":true}\n')
        marker = release / ".install-incomplete"
        if was_incomplete:
            marker.touch(mode=0o600)
        assert check_start_allowed(paths, "ui") is not was_incomplete
        assert check_start_allowed(paths, "cleanup") is not was_incomplete
        contract = root / "paths.env"  # absent contract is permitted for this envelope fixture
        lock = LifecycleLock(root / "host.lock")
        monkeypatch.setattr(admin, "PATHS_FILE", contract)
        monkeypatch.setattr(admin, "LifecycleLock", lambda: lock)
        prior = {
            "knxohui.service": {"active": True, "enabled": True},
            "knxohui-backup-cleanup.service": {"active": False, "enabled": False},
            "knxohui-backup-cleanup.timer": {"active": True, "enabled": False},
        }
        services = {name: dict(flags) for name, flags in prior.items()}

        def shell(argv, **kwargs):
            with lock.inherited(int(kwargs["env"]["KNXOH_LIFECYCLE_FD"])):
                # Component repair does not rebuild or migrate application code;
                # it clears an existing incomplete flag before attempting activation.
                marker.unlink(missing_ok=True)
                value = dict(
                    mode="repair",
                    release=str(release),
                    previous=str(release),
                    release_was_incomplete=was_incomplete,
                    snapshot_file="",
                    ui_start=True,
                    ui_enable=False,
                    cleanup_start=False,
                    cleanup_enable=False,
                    ui_was_active=True,
                    ui_was_enabled=True,
                    cleanup_service_was_active=False,
                    cleanup_timer_was_active=True,
                    cleanup_timer_was_enabled=False,
                )
                Path(kwargs["env"]["KNXOH_BOOTSTRAP_OUTCOME"]).write_text(json.dumps(value))
            return SimpleNamespace(returncode=0)

        failed = False

        def service_command(argv):
            nonlocal failed
            assert argv[0] == "/usr/bin/systemctl", "component repair must not run release code"
            gate = paths.config_dir / ".updater-startup-gate.json"
            if not gate.exists():
                with lock.acquire():
                    pass  # activation and prior-state restoration must not own the disk lease
            action, *rest = argv[1:]
            if action == "restart" and not failed:
                failed = True
                raise subprocess.CalledProcessError(1, argv)
            if len(rest) != 1 or rest[0] not in services:
                return
            if action in ("start", "stop"):
                services[rest[0]]["active"] = action == "start"
            if action in ("enable", "disable"):
                services[rest[0]]["enabled"] = action == "enable"

        monkeypatch.setattr(admin.subprocess, "run", shell)
        monkeypatch.setattr(admin, "_run", service_command)
        with pytest.raises(ValueError, match="prior pair restored"):
            admin.execute_setup(ROOT / "installer", paths, contract, ["--repair"])
        assert failed
        assert marker.exists() is was_incomplete
        assert check_start_allowed(paths, "ui") is not was_incomplete
        assert check_start_allowed(paths, "cleanup") is not was_incomplete
        assert paths.current.resolve() == release
        assert config.read_bytes() == b'{"preserve":true}\n'
        assert services == prior
        assert not (paths.config_dir / ".updater-startup-gate.json").exists()
