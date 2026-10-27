"""Regression tests for the service user's privileged command policy."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_sudoers_policy_only_allows_named_service_actions():
    policy = (ROOT / "installer" / "knxohui.sudoers").read_text(encoding="utf-8")

    assert "knxohui ALL=(root) NOPASSWD: KNOHUI_SERVICE_COMMANDS" in policy
    assert "Cmnd_Alias KNOHUI_SERVICE_COMMANDS" in policy
    policy_rules = "\n".join(
        line for line in policy.splitlines() if not line.lstrip().startswith("#")
    )
    assert "git" not in policy_rules.lower()
    assert "*" not in policy_rules
    assert "ALL=(ALL)" not in policy_rules

    for service in ("openhab.service", "knxohui.service", "evcc.service"):
        for action in ("restart", "is-active"):
            assert f"systemctl {action} {service}" in policy
    for action in ("refresh", "openhab", "evcc"):
        assert f"/usr/local/sbin/knxohui-service-update {action}" in policy


def test_installer_scripts_install_and_validate_the_restricted_policy():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    repair = (ROOT / "fix_permissions.sh").read_text(encoding="utf-8")
    migration = (ROOT / "installer" / "migrate_sudoers.sh").read_text(encoding="utf-8")

    assert "installer/migrate_sudoers.sh" in setup
    assert "migrate_sudoers.sh" in repair
    assert "/usr/local/sbin/knxohui-service-update" in setup
    assert "/usr/local/sbin/knxohui-service-update" in repair
    assert "knxohui.sudoers" in migration
    assert 'visudo -cf "$TEMP_POLICY"' in migration

    assert 'REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"' in setup
    assert '"$REPO_ROOT/requirements.txt"' in setup
    assert "--exclude web_ui/backend/config.json" in setup


def test_installer_runs_provisioner_from_installed_tree():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert '"$BASE/installer/provision_managed_files.py"' in setup
    assert '"$REPO_ROOT/installer/provision_managed_files.py"' not in setup


def test_yaml_provisioning_uses_one_fixed_root_owned_action():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    service_update = (ROOT / "installer" / "service_update.sh").read_text(encoding="utf-8")
    helper = (ROOT / "installer" / "provision_managed_outputs.py").read_text(encoding="utf-8")
    setup_provisioner = (ROOT / "installer" / "provision_managed_files.py").read_text(
        encoding="utf-8"
    )
    repair = (ROOT / "fix_permissions.sh").read_text(encoding="utf-8")
    policy = (ROOT / "installer" / "knxohui.sudoers").read_text(encoding="utf-8")
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert '"$BASE/installer/provision_managed_outputs.py"' in setup
    assert "/usr/local/libexec/knx_to_openhab/provision_managed_outputs.py" in setup
    assert "sudo install -o root -g root -m 0755" in setup
    assert "/usr/local/libexec/knx_to_openhab/provision_managed_outputs.py" in repair
    assert "sudo install -o root -g root -m 0755" in repair
    assert "provision-yaml)" in service_update
    assert "/usr/bin/python3 -I /usr/local/libexec/knx_to_openhab/provision_managed_outputs.py" in (
        service_update
    )
    assert '"$@"' not in service_update
    assert "/usr/local/sbin/knxohui-service-update provision-yaml" in policy
    assert "sudo -n /usr/local/sbin/knxohui-service-update provision-yaml" in update
    assert "Run 'sudo bash $INSTALL_DIR/installer/setup.sh' as an administrator" in update
    assert update.index("provision-yaml") < update.index("# Restart the service")
    assert "managed_openhab_root" in setup_provisioner
    assert "os.fchown(descriptor, 0, service_gid)" in setup_provisioner
    assert "os.fchmod(descriptor, 0o640)" in setup_provisioner
    assert 'config_dir / "managed_openhab_root"' in helper
    assert "_require_trusted_directory_chain" in helper

    lowered_helper = helper.casefold()
    assert "import config" not in lowered_helper
    assert "web_ui" not in lowered_helper
    assert "sys.path" not in lowered_helper


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="the updater retry integration test requires a POSIX shell environment",
)
def test_updater_retries_yaml_provisioning_when_git_is_already_current(tmp_path):
    install_dir = tmp_path / "install"
    backup_dir = tmp_path / "backups"
    bin_dir = tmp_path / "bin"
    (install_dir / ".git").mkdir(parents=True)
    (install_dir / "venv" / "bin").mkdir(parents=True)
    backup_dir.mkdir()
    bin_dir.mkdir()

    updater = install_dir / "update.sh"
    updater.write_text((ROOT / "update.sh").read_text(encoding="utf-8"), encoding="utf-8")
    fake_python = install_dir / "venv" / "bin" / "python"
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        'case " $* " in\n'
        '  *" rev-parse --git-dir "*) printf ".git\\n" ;;\n'
        '  *" rev-parse HEAD "*|*" rev-parse origin/main "*) printf "same-commit\\n" ;;\n'
        '  *" stash "*|*" fetch origin "*) exit 0 ;;\n'
        '  *) printf "unexpected git command: %s\\n" "$*" >&2; exit 90 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    provision_marker = tmp_path / "provision-attempted"
    fake_sudo = bin_dir / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "-n -l" ]]; then exit 0; fi\n'
        'if [[ "$*" == *provision-yaml* ]]; then touch "$PROVISION_MARKER"; exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "LOG_FILE": str(tmp_path / "update.log"),
            "PROVISION_MARKER": str(provision_marker),
        }
    )
    result = subprocess.run(
        ["bash", str(updater)],
        cwd=install_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert provision_marker.exists(), result.stdout + result.stderr
    assert result.returncode != 0, "a provisioning failure must make the updater fail"


def test_permission_repair_restores_external_runtime_data_ownership():
    repair = (ROOT / "fix_permissions.sh").read_text(encoding="utf-8")

    assert "get_paths; print(get_paths().data_dir)" in repair
    assert 'sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"' in repair


def test_web_updater_stops_until_legacy_sudoers_policy_is_migrated():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "sudo -n -l" in update
    assert "/usr/bin/git|/bin/git" in update
    assert "installer/migrate_sudoers.sh" in update


def test_web_updater_checks_external_credentials_before_backup_or_git_changes():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    preflight = update.index("CREDENTIAL_CHECK=")
    assert "external Web UI config.json or secrets.env is missing" in update
    assert "valid external Argon2id password hash is required" in update
    assert "sudo bash $INSTALL_DIR/installer/setup.sh" in update
    assert preflight < update.index("Creating backup of current installation")
    assert preflight < update.index('git -c "safe.directory=$INSTALL_DIR" stash')
    assert preflight < update.index('git -c "safe.directory=$INSTALL_DIR" fetch origin')


def test_update_script_never_elevates_git_or_uses_a_global_safe_directory():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "sudo git" not in update
    assert "sudo -u" not in update
    assert "safe.directory='*'" not in update
    assert "git config --global" not in update
    assert 'git -c "safe.directory=$INSTALL_DIR"' in update
    assert 'sudo systemctl is-active "$SERVICE_NAME" > /dev/null' in update
    assert "systemctl is-active --quiet" not in update


def test_privilege_scripts_have_valid_bash_syntax():
    if shutil.which("bash") is None:
        return

    for path in (
        ROOT / "installer" / "setup.sh",
        ROOT / "installer" / "migrate_sudoers.sh",
        ROOT / "installer" / "service_update.sh",
        ROOT / "fix_permissions.sh",
        ROOT / "update.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


def test_sudoers_policy_parses_when_visudo_is_available():
    visudo = shutil.which("visudo")
    if visudo is None:
        return

    policy = ROOT / "installer" / "knxohui.sudoers"
    result = subprocess.run(
        [visudo, "-cf", str(policy)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
