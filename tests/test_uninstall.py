import os
import shlex
import shutil
import subprocess
from io import StringIO
from pathlib import Path, PurePosixPath
from textwrap import dedent

import pytest

from installer.uninstall import (
    UninstallError,
    UninstallPaths,
    resolve_uninstall_paths,
    run_uninstall,
)

ROOT = Path(__file__).resolve().parents[1]


def test_resolves_canonical_defaults_when_saved_paths_file_is_missing(tmp_path):
    paths = resolve_uninstall_paths({}, tmp_path / "missing-paths.env")

    assert paths.install_dir == PurePosixPath("/opt/knx_to_openhab")
    assert paths.config_dir == PurePosixPath("/etc/knx_to_openhab")
    assert paths.data_dir == PurePosixPath("/var/lib/knx_to_openhab")
    assert paths.backup_dir == PurePosixPath("/var/backups/knx_to_openhab")


def test_reads_quoted_paths_without_evaluating_shell_metacharacters(tmp_path):
    marker = tmp_path / "should-not-exist"
    paths_file = tmp_path / "paths.env"
    expected = f"/srv/knx app $cash 'quoted' ; touch {marker.as_posix()} \\path"
    paths_file.write_text(f"KNXOH_INSTALL_DIR={shlex.quote(expected)}\n", encoding="utf-8")

    paths = resolve_uninstall_paths({}, paths_file)

    assert str(paths.install_dir) == expected
    assert not marker.exists()


def test_environment_values_override_saved_paths(tmp_path):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text('KNXOH_INSTALL_DIR="/srv/saved"\n', encoding="utf-8")

    paths = resolve_uninstall_paths({"KNXOH_INSTALL_DIR": "/srv/override"}, paths_file)

    assert paths.install_dir == PurePosixPath("/srv/override")


@pytest.mark.parametrize(
    "environment, match",
    [
        ({"KNXOH_INSTALL_DIR": "/"}, "filesystem root"),
        ({"KNXOH_INSTALL_DIR": "/etc"}, "system directory"),
        ({"KNXOH_INSTALL_DIR": "relative/install"}, "absolute"),
        ({"KNXOH_DATA_DIR": "/opt/knx_to_openhab/data"}, "overlap"),
        ({"KNXOH_BACKUP_DIR": "/var/lib/knx_to_openhab/jobs"}, "overlap"),
    ],
)
def test_rejects_unsafe_or_overlapping_paths_before_uninstall(tmp_path, environment, match):
    with pytest.raises(UninstallError, match=match):
        resolve_uninstall_paths(environment, tmp_path / "missing-paths.env")


def _custom_paths():
    return UninstallPaths(
        install_dir=PurePosixPath("/opt/custom-knxoh"),
        config_dir=PurePosixPath("/etc/custom-knxoh"),
        data_dir=PurePosixPath("/var/lib/custom-knxoh"),
        backup_dir=PurePosixPath("/var/backups/custom-knxoh"),
    )


def _run_uninstall(tmp_path, answers, *, purge=False, command_runner=None):
    paths = _custom_paths()
    env = {
        "KNXOH_INSTALL_DIR": str(paths.install_dir),
        "KNXOH_CONFIG_DIR": str(paths.config_dir),
        "KNXOH_DATA_DIR": str(paths.data_dir),
        "KNXOH_BACKUP_DIR": str(paths.backup_dir),
    }
    commands = []
    prompts = iter(answers)
    output = StringIO()
    result = run_uninstall(
        ["--purge"] if purge else [],
        env=env,
        paths_file=tmp_path / "paths.env",
        confirm=lambda _prompt: next(prompts),
        command_runner=command_runner or (lambda command: commands.append(tuple(command)) or 0),
        output=output,
    )
    return result, commands, output.getvalue(), paths


def test_default_uninstall_confirms_and_retains_external_user_data(tmp_path):
    result, commands, output, paths = _run_uninstall(tmp_path, ["UNINSTALL"])

    assert result == 0
    assert ("sudo", "rm", "-rf", "--", str(paths.install_dir)) not in commands
    assert not any(
        command[-1] in {str(paths.config_dir), str(paths.data_dir), str(paths.backup_dir)}
        for command in commands
    )
    assert not any("userdel" in command for command in commands)
    assert all(str(path) in output for path in (paths.config_dir, paths.data_dir, paths.backup_dir))
    for target in (
        "/etc/systemd/system/knxohui.service",
        "/etc/sudoers.d/knxohui",
    ):
        assert target in output
    assert "retained for offline recovery" in output


def test_declining_uninstall_runs_no_commands(tmp_path):
    result, commands, output, _paths = _run_uninstall(tmp_path, ["no"])

    assert result == 0
    assert commands == []
    assert "cancel" in output.lower()


def test_purge_requires_exact_second_confirmation_before_any_command(tmp_path):
    result, commands, output, _paths = _run_uninstall(tmp_path, ["UNINSTALL", "purge"], purge=True)

    assert result == 0
    assert commands == []
    assert "cancel" in output.lower()


def test_confirmed_purge_removes_only_configured_data_and_service_user(tmp_path):
    result, commands, _output, paths = _run_uninstall(tmp_path, ["UNINSTALL", "PURGE"], purge=True)

    assert result == 0
    for path in (paths.install_dir, paths.config_dir, paths.data_dir, paths.backup_dir):
        assert ("sudo", "rm", "-rf", "--", str(path)) in commands
    assert ("sudo", "userdel", "knxohui") in commands


def test_purge_checks_recovery_evidence_after_stopping_updater_before_any_removal(tmp_path):
    commands = []

    def pending_journal(command):
        commands.append(tuple(command))
        return 1 if command[:2] == ("sudo", "test") else 0

    result, _, output, _ = _run_uninstall(
        tmp_path, ["UNINSTALL", "PURGE"], purge=True, command_runner=pending_journal
    )
    assert result == 2
    check = next(index for index, command in enumerate(commands) if "test" in command)
    assert commands.index(("sudo", "systemctl", "stop", "knxohui-update.service")) < check
    assert commands.index(("sudo", "systemctl", "stop", "knxohui-update-recovery.service")) < check
    assert not any("rm" in command or "userdel" in command for command in commands)
    assert "evidence" in output


def test_purge_retains_dangling_private_state_link_as_unsafe_evidence(tmp_path):
    commands = []

    def dangling_state(command):
        commands.append(tuple(command))
        return 1 if command[:4] == ("sudo", "test", "!", "-L") else 0

    result, _, output, _ = _run_uninstall(
        tmp_path, ["UNINSTALL", "PURGE"], purge=True, command_runner=dangling_state
    )
    assert result == 2
    assert not any("rm" in command or "userdel" in command for command in commands)
    assert "evidence" in output


def test_failed_config_purge_stops_before_removing_runtime_and_backups(tmp_path):
    commands = []

    def fail_config_removal(command):
        commands.append(tuple(command))
        return 1 if command[-1] == "/etc/custom-knxoh" else 0

    result, _recorded_commands, output, paths = _run_uninstall(
        tmp_path,
        ["UNINSTALL", "PURGE"],
        purge=True,
        command_runner=fail_config_removal,
    )

    assert result == 1
    assert ("sudo", "rm", "-rf", "--", str(paths.config_dir)) in commands
    assert ("sudo", "rm", "-rf", "--", str(paths.data_dir)) not in commands
    assert ("sudo", "rm", "-rf", "--", str(paths.backup_dir)) not in commands
    assert "errors" in output


@pytest.mark.skipif(os.name != "posix", reason="symlink path guard is POSIX-specific")
def test_rejects_symlinked_install_path(tmp_path):
    real_install = tmp_path / "real-install"
    real_install.mkdir()
    link = tmp_path / "install-link"
    link.symlink_to(real_install, target_is_directory=True)

    with pytest.raises(UninstallError, match="symlink"):
        resolve_uninstall_paths(
            {"KNXOH_INSTALL_DIR": str(link)},
            tmp_path / "missing-paths.env",
        )


def _fake_sudo(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text(
        dedent("""\
            #!/bin/sh
            set -eu
            action=$1
            shift
            case "$action" in
                systemctl|userdel)
                    exit 0
                    ;;
                rm)
                    flags=$1
                    shift
                    [ "$1" = "--" ]
                    shift
                    for target in "$@"; do
                        case "$target" in
                            /etc/systemd/system/knxohui.service|\
                            /etc/systemd/system/knxohui-backup-cleanup.service|\
                            /etc/systemd/system/knxohui-backup-cleanup.timer|\
                            /etc/systemd/system/knxohui-update.service|\
                            /usr/local/libexec/knx_to_openhab|\
                            /usr/local/sbin/knxohui-service-update|\
                            /etc/sudoers.d/knxohui)
                                ;;
                            "$TEST_ROOT"/*)
                                /bin/rm "$flags" -- "$target"
                                ;;
                            *)
                                echo "blocked unexpected deletion: $target" >&2
                                exit 98
                                ;;
                        esac
                    done
                    ;;
                *)
                    echo "blocked unexpected command: $action" >&2
                    exit 99
                    ;;
            esac
            """),
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    return bin_dir


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires a non-root POSIX host and executable fake sudo",
)
def test_shell_entrypoint_preserves_external_data_by_default(tmp_path):
    install_dir = tmp_path / "install"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    for directory in (install_dir, config_dir, data_dir, backup_dir):
        directory.mkdir()
        (directory / "keep.txt").write_text("retained", encoding="utf-8")
    bin_dir = _fake_sudo(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(bin_dir) + os.pathsep + environment.get("PATH", ""),
            "TEST_ROOT": str(tmp_path),
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(tmp_path / "missing-paths.env"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "uninstall.sh")],
        input="UNINSTALL\n",
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not install_dir.exists()
    for directory in (config_dir, data_dir, backup_dir):
        assert (directory / "keep.txt").read_text(encoding="utf-8") == "retained"


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires a non-root POSIX host and executable fake sudo",
)
def test_shell_entrypoint_purges_only_after_both_confirmations(tmp_path):
    install_dir = tmp_path / "install"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    for directory in (install_dir, config_dir, data_dir, backup_dir):
        directory.mkdir()
        (directory / "keep.txt").write_text("remove", encoding="utf-8")
    bin_dir = _fake_sudo(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(bin_dir) + os.pathsep + environment.get("PATH", ""),
            "TEST_ROOT": str(tmp_path),
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(tmp_path / "missing-paths.env"),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "uninstall.sh"), "--purge"],
        input="UNINSTALL\nPURGE\n",
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert all(
        not directory.exists() for directory in (install_dir, config_dir, data_dir, backup_dir)
    )


@pytest.mark.skipif(os.name != "posix", reason="Bash syntax check requires POSIX")
def test_uninstall_shell_entrypoint_has_valid_bash_syntax():
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-n", str(ROOT / "uninstall.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    os.name != "posix", reason="piped launcher test requires POSIX process semantics"
)
def test_piped_launcher_does_not_run_helper_from_the_callers_working_directory(tmp_path):
    bin_dir = tmp_path / "bin"
    local_installer = tmp_path / "installer"
    bin_dir.mkdir()
    local_installer.mkdir()
    (local_installer / "uninstall.py").write_text(
        "print('caller-controlled helper')\n", encoding="utf-8"
    )
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = -o ]; then shift; output=$1; fi\n'
        "  shift\n"
        "done\n"
        "printf '%s\\n' \"print('downloaded helper')\" > \"$output\"\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
    environment.pop("KNXOH_PATHS_FILE", None)

    result = subprocess.run(
        [shutil.which("bash") or "bash"],
        input=(ROOT / "uninstall.sh").read_text(encoding="utf-8"),
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "downloaded helper" in result.stdout
    assert "caller-controlled helper" not in result.stdout
