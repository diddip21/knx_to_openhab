"""Regression tests for the service user's privileged command policy."""

import shutil
import subprocess
from pathlib import Path

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
    for output_format in ("legacy", "yaml"):
        assert f"/usr/local/sbin/knxohui-retire-managed-outputs {output_format}" in policy


def test_installer_scripts_install_and_validate_the_restricted_policy():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    repair = (ROOT / "fix_permissions.sh").read_text(encoding="utf-8")
    migration = (ROOT / "installer" / "migrate_sudoers.sh").read_text(encoding="utf-8")

    assert "installer/migrate_sudoers.sh" in setup
    assert "migrate_sudoers.sh" in repair
    assert "/usr/local/sbin/knxohui-service-update" in setup
    assert "/usr/local/sbin/knxohui-service-update" in repair
    assert "/usr/local/sbin/knxohui-retire-managed-outputs" in setup
    assert "/usr/local/sbin/knxohui-retire-managed-outputs" in repair
    assert "knxohui.sudoers" in migration
    assert 'visudo -cf "$TEMP_POLICY"' in migration

    assert 'REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"' in setup
    assert '"$REPO_ROOT/requirements.txt"' in setup
    assert "--exclude /web_ui/backend/config.json" in setup


def test_installer_runs_provisioner_from_installed_tree():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert '"$BASE/installer/provision_managed_files.py"' in setup
    assert '"$REPO_ROOT/installer/provision_managed_files.py"' not in setup


def test_root_retirement_helper_does_not_import_writable_application_code():
    helper = (ROOT / "installer" / "retire_managed_outputs.py").read_text(encoding="utf-8")

    assert "from web_ui" not in helper
    assert "sys.path.insert" not in helper
    assert "managed_outputs.json" in helper


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
    assert "interactive SSH terminal" in update
    assert preflight < update.index("Creating backup of current installation")
    assert preflight < update.index('git -c "safe.directory=$INSTALL_DIR" stash')
    assert preflight < update.index('git -c "safe.directory=$INSTALL_DIR" fetch origin')


def test_setup_checks_for_terminal_before_stopping_services():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert "exec 3<>/dev/tty" in setup
    assert "No service, package or runtime data was changed." in setup
    assert setup.index("exec 3<>/dev/tty") < setup.index(
        'echo "Stopping the Web UI and backup cleanup during migration"'
    )

def test_setup_restores_previously_active_services_after_failure():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert "PREVIOUSLY_ACTIVE_UNITS" in setup
    assert "trap restore_previous_services EXIT" in setup
    assert 'sudo systemctl start "$unit"' in setup
    assert setup.index("trap restore_previous_services EXIT") < setup.index(
        'echo "Stopping the Web UI and backup cleanup during migration"'
    )
    assert "SETUP_COMPLETED=1" in setup


def test_setup_runs_password_prompt_without_nested_sudo_when_already_root():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert 'if [[ "$EUID" -eq 0 ]]; then' in setup
    assert '"$BASE/venv/bin/python" "$BASE/installer/configure_auth.py"' in setup


def test_web_updater_rolls_back_if_updated_service_fails_health_check():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "wait_for_service_active()" in update
    assert "restore_previous_release()" in update
    assert (
        'git -c "safe.directory=$INSTALL_DIR" reset --hard "$CURRENT_COMMIT"'
        in update
    )
    assert 'if ! wait_for_service_active; then' in update
    assert update.index('if ! wait_for_service_active; then') < update.index(
        'log "Update completed successfully!"'
    )


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
