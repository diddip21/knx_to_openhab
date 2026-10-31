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
    assert "interactive SSH terminal" in update
    restart_index = update.index('log "Restarting $SERVICE_NAME..."')
    assert update.index("provision-yaml") < restart_index
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
    assert "interactive SSH terminal" in update
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


def test_setup_preflights_credentials_before_stopping_services():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert 'elif id -u "$SERVICE_USER" >/dev/null 2>&1; then' in setup
    assert 'AUTH_PREFLIGHT_COMMAND=(sudo -u "$SERVICE_USER" env' in setup
    assert 'AUTH_PREFLIGHT_COMMAND=(env "PYTHONPATH=$BASE" "$BASE/venv/bin/python")' in setup
    assert "No service, package or runtime data was changed." in setup
    assert "generate one and show it once" in setup
    assert setup.index(
        'echo "The existing Web UI credential configuration is invalid."'
    ) < setup.index('echo "Stopping the Web UI and backup cleanup during migration"')


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
    assert 'git -c "safe.directory=$INSTALL_DIR" reset --hard "$CURRENT_COMMIT"' in update
    assert "if ! wait_for_service_active; then" in update
    assert update.index("if ! wait_for_service_active; then") < update.index(
        'log "Update completed successfully!"'
    )


def test_setup_preflight_generates_for_missing_credentials_and_rejects_invalid_config(tmp_path):
    setup_script = ROOT / "installer" / "setup.sh"
    for status, message in (
        (1, "generate one and show it once"),
        (2, "The existing Web UI credential configuration is invalid."),
    ):
        case = tmp_path / f"preflight-{status}"
        base = case / "opt" / "knx_to_openhab"
        config = case / "etc" / "knx_to_openhab"
        data = case / "var" / "lib" / "knx_to_openhab"
        backups = case / "var" / "backups" / "knx_to_openhab"
        fake_bin = case / "bin"
        python = base / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        fake_bin.mkdir(parents=True)
        wrong_identity_status = 2 if status == 1 else 1
        python.write_text(
            "#!/bin/sh\n"
            'if [ "$SETUP_TEST_EXPECT_SERVICE" = 1 ] && '
            '[ "$SETUP_TEST_PREFLIGHT_AS_SERVICE" != 1 ]; then\n'
            f"  exit {wrong_identity_status}\n"
            "fi\n"
            f"exit {status}\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        fake_id = fake_bin / "id"
        fake_id.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = -u ] && [ "$2" = knxohui ]; then echo 997; exit 0; fi\n'
            "exit 1\n",
            encoding="utf-8",
        )
        fake_id.chmod(0o755)
        sudo = fake_bin / "sudo"
        sudo.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = -u ] && [ "$2" = knxohui ]; then\n'
            "  shift 2\n"
            '  if [ "$1" = env ]; then\n'
            '    echo preflight >> "$SETUP_TEST_SUDO_LOG"\n'
            '    SETUP_TEST_PREFLIGHT_AS_SERVICE=1 exec "$@"\n'
            "  fi\n"
            "fi\n"
            'echo mutation >> "$SETUP_TEST_SUDO_LOG"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        sudo.chmod(0o755)
        fake_rsync = fake_bin / "rsync"
        fake_rsync.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_rsync.chmod(0o755)
        sudo_log = case / "sudo-called"
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(fake_bin) + os.pathsep + env["PATH"],
                "SETUP_TEST_SUDO_LOG": str(sudo_log),
                "SETUP_TEST_EXPECT_SERVICE": "0" if os.geteuid() == 0 else "1",
                "KNXOH_INSTALL_DIR": str(base),
                "KNXOH_CONFIG_DIR": str(config),
                "KNXOH_DATA_DIR": str(data),
                "KNXOH_BACKUP_DIR": str(backups),
            }
        )

        result = subprocess.run(
            ["bash", str(setup_script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        sudo_calls = sudo_log.read_text(encoding="utf-8").splitlines() if sudo_log.exists() else []
        if status == 1:
            assert result.returncode != 4
            assert message in result.stdout
            assert "Stopping the Web UI" in result.stdout
            assert "Credential migration needs an interactive terminal." not in result.stderr
            assert sudo_calls and "mutation" in sudo_calls
        else:
            assert result.returncode == 4
            assert message in result.stderr
            assert "No service, package or runtime data was changed." in result.stderr
            assert sudo_calls in ([], ["preflight"])
        assert not (config / "secrets.env").exists()
        assert not (config.parent / "paths.env").exists()


def test_update_restores_previous_commit_if_service_health_check_fails(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    install = tmp_path / "install"
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    backup_dir = tmp_path / "backups"
    config_dir = tmp_path / "config"
    paths_file = tmp_path / "paths.env"
    for directory in (seed, fake_bin, state, backup_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    def git(*args, cwd=None):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )

    (config_dir / "config.json").write_text('{"auth":{"enabled":false}}', encoding="utf-8")
    (config_dir / "secrets.env").write_text("\n", encoding="utf-8")
    paths_file.write_text("", encoding="utf-8")

    git("init", "--bare", "--initial-branch=main", str(remote))
    git("init", "--initial-branch=main", str(seed))
    git("config", "user.name", "Update recovery test", cwd=seed)
    git("config", "user.email", "update-test@example.invalid", cwd=seed)
    (seed / "requirements.txt").write_text("old-dependency\n", encoding="utf-8")
    git("add", ".", cwd=seed)
    git("commit", "-m", "old release", cwd=seed)
    previous_commit = git("rev-parse", "HEAD", cwd=seed).stdout.strip()
    git("remote", "add", "origin", str(remote), cwd=seed)
    git("push", "-u", "origin", "main", cwd=seed)
    git("clone", "--branch", "main", str(remote), str(install))
    (seed / "requirements.txt").write_text("new-dependency\n", encoding="utf-8")
    git("add", "requirements.txt", cwd=seed)
    git("commit", "-m", "candidate release", cwd=seed)
    git("push", "origin", "main", cwd=seed)

    venv_bin = install / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    for executable in ("python", "pip"):
        path = venv_bin / executable
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "-n" && "$2" == "-l" ]]; then\n'
        '  echo "systemctl restart knxohui.service is permitted"\n  exit 0\nfi\n'
        'if [[ "$*" == *provision-yaml* ]]; then exit 0; fi\n'
        'if [[ "$1" == "systemctl" && "$2" == "restart" ]]; then\n'
        "  count=0\n"
        '  [[ -f "$UPDATE_TEST_STATE/restarts" ]] && count=$(<"$UPDATE_TEST_STATE/restarts")\n'
        '  count=$((count + 1))\n  echo "$count" > "$UPDATE_TEST_STATE/restarts"\n'
        "  if (( count == 1 )); then exit 0; fi\n"
        '  touch "$UPDATE_TEST_STATE/active"\n  exit 0\nfi\n'
        'if [[ "$1" == "systemctl" && "$2" == "is-active" ]]; then\n'
        '  [[ -f "$UPDATE_TEST_STATE/active" ]] || exit 3\n'
        "  count=0\n"
        '  [[ -f "$UPDATE_TEST_STATE/active-checks" ]] && count=$(<"$UPDATE_TEST_STATE/active-checks")\n'
        "  count=$((count + 1))\n"
        '  echo "$count" > "$UPDATE_TEST_STATE/active-checks"\n  exit 0\nfi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    log_file = tmp_path / "update.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "UPDATE_TEST_STATE": str(state),
            "INSTALL_DIR": str(install),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "LOG_FILE": str(log_file),
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "update.sh")],
        cwd=install,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    current_commit = git("rev-parse", "HEAD", cwd=install).stdout.strip()
    log = log_file.read_text(encoding="utf-8")

    assert result.returncode == 1
    assert current_commit == previous_commit
    assert (state / "active").is_file()
    assert (state / "restarts").read_text(encoding="utf-8").strip() == "2"
    assert int((state / "active-checks").read_text(encoding="utf-8")) >= 3
    assert "The updated service did not become active." in log
    assert "Previous version restored and service is active." in log


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
