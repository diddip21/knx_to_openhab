"""Regression tests for the service user's privileged command policy."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
    assert "/usr/local/sbin/knxohui-service-update start-web-update" in policy


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
    assert '"$BASE/installer/launch_update.sh"' in setup
    assert '"$BASE/installer/knxohui-update.service"' in setup


def test_updater_runs_in_its_own_systemd_unit_outside_the_web_service_cgroup():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    helper = (ROOT / "installer" / "service_update.sh").read_text(encoding="utf-8")
    policy = (ROOT / "installer" / "knxohui.sudoers").read_text(encoding="utf-8")
    unit = (ROOT / "installer" / "knxohui-update.service").read_text(encoding="utf-8")
    launcher = (ROOT / "installer" / "launch_update.sh").read_text(encoding="utf-8")
    updater = (ROOT / "web_ui" / "backend" / "updater.py").read_text(encoding="utf-8")

    assert "start-web-update)" in helper
    assert "systemctl start --no-block knxohui-update.service" in helper
    assert "/usr/local/sbin/knxohui-service-update start-web-update" in policy
    assert "knxohui-update.service" in setup
    assert "User=knxohui" in unit
    assert "ExecStart=/usr/local/libexec/knx_to_openhab/launch_update.sh" in unit
    assert "run_update_request.py" in launcher
    assert "subprocess.Popen" not in updater
    assert "start-web-update" in updater


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
    restart_index = update.index('log "Restarting $SERVICE_NAME on release')
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
def test_transactional_update_no_op_does_not_backup_or_provision(tmp_path):
    install_dir = tmp_path / "install"
    release_dir = install_dir / "releases" / "1.4.0"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    bin_dir = tmp_path / "bin"
    (release_dir / "venv" / "bin").mkdir(parents=True)
    config_dir.mkdir()
    data_dir.mkdir()
    bin_dir.mkdir()
    backup_blocker = tmp_path / "backup-is-disabled"
    backup_blocker.write_text("a no-op must not try to create this directory", encoding="utf-8")
    config_file = config_dir / "config.json"
    config_file.write_text('{"auth":{"enabled":false}}', encoding="utf-8")
    (config_dir / "secrets.env").write_text("\n", encoding="utf-8")
    (data_dir / "generator.json").write_text('{"general":{}}', encoding="utf-8")
    paths_file = tmp_path / "paths.env"
    paths_file.write_text("", encoding="utf-8")

    commit_hash = "a" * 40
    (release_dir / "version.json").write_text(
        f'{{"release_tag":"v1.4.0","commit_hash":"{commit_hash}"}}',
        encoding="utf-8",
    )
    shutil.copy2(ROOT / "knxoh_paths.py", release_dir / "knxoh_paths.py")
    (release_dir / "web_ui/backend").mkdir(parents=True)
    shutil.copy2(ROOT / "web_ui/backend/auth.py", release_dir / "web_ui/backend/auth.py")
    real_python = shlex.quote(sys.executable)
    fake_python = release_dir / "venv" / "bin" / "python"
    fake_python.write_text(f'#!/bin/sh\nexec {real_python} "$@"\n', encoding="utf-8")
    fake_python.chmod(0o755)
    (install_dir / "current").symlink_to("releases/1.4.0")

    updater = install_dir / "update.sh"
    updater.write_text((ROOT / "update.sh").read_text(encoding="utf-8"), encoding="utf-8")

    provision_marker = tmp_path / "provision-attempted"
    fake_sudo = bin_dir / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "-n -l" ]]; then echo "NOPASSWD: limited service commands"; exit 0; fi\n'
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
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_blocker),
            "KNXOH_PATHS_FILE": str(paths_file),
            "LOG_FILE": str(tmp_path / "update.log"),
            "RELEASE_TAG": "v1.4.0",
            "RELEASE_COMMIT_HASH": commit_hash,
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

    assert result.returncode == 0, result.stdout + result.stderr
    assert not provision_marker.exists()
    assert backup_blocker.is_file()
    assert "Already running selected release v1.4.0." in result.stdout


def test_permission_repair_restores_external_runtime_data_ownership():
    repair = (ROOT / "fix_permissions.sh").read_text(encoding="utf-8")

    assert "get_paths; print(get_paths().data_dir)" in repair
    assert 'sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"' in repair


def test_web_updater_stops_until_legacy_sudoers_policy_is_migrated():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "sudo -n -l" in update
    assert "/usr/bin/git|/bin/git" in update
    assert "installer/migrate_sudoers.sh" in update


def test_web_updater_checks_external_credentials_before_backup_or_release_changes():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    preflight = update.index("CREDENTIAL_CHECK=")
    assert "external Web UI config.json or secrets.env is missing" in update
    assert "valid external Argon2id password hash is required" in update
    assert "sudo bash $INSTALL_DIR/installer/setup.sh" in update
    assert "interactive SSH terminal" in update
    backup = update.index("Creating and validating pre-update backup")
    assert preflight < backup
    assert backup < update.index('"$APP_DIR/installer/prepare_release.py"')
    assert 'git -c "safe.directory=$INSTALL_DIR" stash' not in update


def test_update_script_never_elevates_git_or_uses_a_global_safe_directory():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert "sudo git" not in update
    assert "sudo -u" not in update
    assert "safe.directory='*'" not in update
    assert "git config --global" not in update
    assert 'git -c "safe.directory=$INSTALL_DIR"' in update
    assert 'sudo systemctl is-active "$SERVICE_NAME" > /dev/null' in update
    assert "systemctl is-active --quiet" not in update


def test_web_updater_uses_only_verified_stable_release_assets():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")

    assert 'RELEASE_TAG="${RELEASE_TAG:-}"' in update
    assert 'RELEASE_COMMIT_HASH="${RELEASE_COMMIT_HASH:-}"' in update
    assert '"$APP_DIR/installer/prepare_release.py"' in update
    assert 'mv -Tf -- "$TEMP_CURRENT_LINK" "$CURRENT_LINK"' in update
    assert 'git -c "safe.directory=$INSTALL_DIR" fetch' not in update
    assert 'checkout --detach "$RELEASE_TAG"' not in update
    assert "origin/main" not in update
    assert "pull origin main" not in update


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

    assert "wait_for_service_health()" in update
    assert "restore_previous_release()" in update
    assert 'mv -Tf -- "$TEMP_CURRENT_LINK" "$CURRENT_LINK"' in update
    assert "if ! wait_for_service_health; then" in update
    assert update.index("if ! wait_for_service_health; then") < update.index(
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


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None or shutil.which("flock") is None,
    reason="the release updater integration test requires Linux utilities",
)
@pytest.mark.parametrize("use_default_port", [False, True])
@pytest.mark.parametrize(
    ("health_check_fails", "activation_fails", "dependency_fails"),
    [(True, False, False), (False, False, False), (False, True, False), (False, False, True)],
)
def test_transactional_update_rolls_back_or_prunes_releases_after_health_check(
    tmp_path, use_default_port, health_check_fails, activation_fails, dependency_fails
):
    install = tmp_path / "install"
    fake_bin = tmp_path / "bin"
    state = tmp_path / "state"
    backup_dir = tmp_path / "backups"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    paths_file = tmp_path / "paths.env"
    for directory in (
        install / "installer",
        install / "web_ui/backend",
        install / "releases",
        fake_bin,
        state,
        backup_dir,
        config_dir,
        data_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    stale_staging = install / "releases" / ".staging-v1.0.0-orphaned"
    stale_staging.mkdir()
    (stale_staging / "partial-release.tar").write_text("interrupted", encoding="utf-8")

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/status":
                self.send_error(404)
                return
            if health_check_fails and (install / "current").is_symlink():
                status, payload = 503, b'{"status":"starting"}'
            else:
                status, payload = 200, b'{"status":"ok"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    health_host = "127.0.0.2"
    try:
        server = HTTPServer((health_host, 8085 if use_default_port else 0), HealthHandler)
    except OSError as error:
        if use_default_port:
            pytest.skip(f"the default Web UI port 8085 is already in use: {error}")
        raise
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]

    web_config = {"auth": {"enabled": False}, "bind_host": health_host}
    if not use_default_port:
        web_config["port"] = port
    (config_dir / "config.json").write_text(json.dumps(web_config), encoding="utf-8")
    if not health_check_fails and not activation_fails and not dependency_fails:
        stale_release = install / "releases" / "old-release"
        stale_release.mkdir(parents=True)
        (stale_release / "version.json").write_text(
            json.dumps({"release_tag": "v0.9.0"}), encoding="utf-8"
        )
    (config_dir / "secrets.env").write_text("\n", encoding="utf-8")
    (data_dir / "generator.json").write_text('{"general":{}}', encoding="utf-8")
    (data_dir / "jobs").mkdir()
    (data_dir / "jobs/user.json").write_text("preserved", encoding="utf-8")
    paths_file.write_text("", encoding="utf-8")

    shutil.copy2(ROOT / ".gitignore", install / ".gitignore")
    (install / "requirements.txt").write_text("legacy-dependency\n", encoding="utf-8")
    shutil.copy2(ROOT / "update.sh", install / "update.sh")
    shutil.copy2(ROOT / "knxoh_paths.py", install / "knxoh_paths.py")
    shutil.copy2(
        ROOT / "installer/create_update_backup.py", install / "installer/create_update_backup.py"
    )
    shutil.copy2(ROOT / "installer/web_ui_endpoint.py", install / "installer/web_ui_endpoint.py")
    shutil.copy2(ROOT / "web_ui/backend/auth.py", install / "web_ui/backend/auth.py")
    shutil.copy2(ROOT / "web_ui/backend/storage.py", install / "web_ui/backend/storage.py")
    (install / "web_ui/backend/config.json").write_text(
        '{"auth":{"enabled":false},"legacy":"shipped"}', encoding="utf-8"
    )
    (install / "config.json").write_text('{"legacy":"shipped"}', encoding="utf-8")

    release_helper = install / "installer/prepare_release.py"
    release_helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "from pathlib import Path\n"
        "def argument(name): return sys.argv[sys.argv.index(name) + 1]\n"
        "tag = argument('--tag')\n"
        "version = tag[1:]\n"
        "app = Path(argument('--destination')) / ('knx_to_openhab-' + version)\n"
        "files = {\n"
        "  'requirements.txt': 'unused\\n',\n"
        "  'update.sh': '#!/bin/bash\\n',\n"
        "  'knxoh_paths.py': '# path helper\\n',\n"
        "  'installer/create_update_backup.py': '# backup helper\\n',\n"
        "  'installer/prepare_release.py': '# release helper\\n',\n"
        "  'installer/launch_web.sh': '#!/bin/bash\\n',\n"
        "  'web_ui/backend/app.py': '# application\\n',\n"
        "  'web_ui/backend/updater.py': '# updater\\n',\n"
        "  'web_ui/__init__.py': '',\n"
        "  'web_ui/backend/__init__.py': '',\n"
        "}\n"
        "for relative, content in files.items():\n"
        "  target = app / relative\n"
        "  target.parent.mkdir(parents=True, exist_ok=True)\n"
        "  target.write_text(content, encoding='utf-8')\n"
        "for relative in ('knxoh_paths.py', 'installer/web_ui_endpoint.py',\n"
        "                 'web_ui/backend/auth.py', 'web_ui/backend/storage.py'):\n"
        "  target = app / relative\n"
        "  target.parent.mkdir(parents=True, exist_ok=True)\n"
        "  target.write_bytes((Path.cwd() / relative).read_bytes())\n"
        "metadata = {\n"
        "  'release_tag': tag, 'version': version,\n"
        "  'commit_hash': argument('--commit-hash'),\n"
        "  'commit_date': argument('--commit-date'),\n"
        "  'commit_message': argument('--commit-message'),\n"
        "  'author': argument('--author'),\n"
        "  'repository': argument('--repository'), 'branch': tag,\n"
        "}\n"
        "(app / 'version.json').write_text(json.dumps(metadata), encoding='utf-8')\n"
        "print(app)\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "init", "--initial-branch=main", str(install)], check=True)
    subprocess.run(
        ["git", "-C", str(install), "config", "user.name", "Update recovery test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(install), "config", "user.email", "update-test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(install), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(install), "commit", "-m", "legacy release"],
        check=True,
    )
    (install / "config.json").write_text('{"general":{"legacy":"custom"}}', encoding="utf-8")
    (install / "web_ui/backend/config.json").write_text(
        '{"auth":{"enabled":false},"legacy":"custom"}', encoding="utf-8"
    )

    real_python = shlex.quote(sys.executable)
    python = install / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec {real_python} "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    pip = install / "venv/bin/pip"
    pip.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "install" && "${DEPENDENCY_TEST_FAIL:-0}" == "1" ]]; then exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    pip.chmod(0o755)

    if activation_fails or dependency_fails:
        previous_release = install / "releases/old-release"
        for relative in (
            "knxoh_paths.py",
            "installer/create_update_backup.py",
            "installer/prepare_release.py",
            "web_ui/backend/auth.py",
            "web_ui/backend/storage.py",
        ):
            source = install / relative
            target = previous_release / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (previous_release / "version.json").write_text(
            json.dumps({"release_tag": "v1.1.0", "commit_hash": "b" * 40}),
            encoding="utf-8",
        )
        (previous_release / "release-marker.txt").write_text("previous release", encoding="utf-8")
        for executable in ("python", "pip"):
            target = previous_release / "venv/bin" / executable
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(install / "venv/bin" / executable, target)
        (install / "current").symlink_to("releases/old-release", target_is_directory=True)

    python3 = fake_bin / "python3"
    python3.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1:3] == ['-m', 'venv']:\n"
        "  bin_dir = Path(sys.argv[3]) / 'bin'\n"
        "  bin_dir.mkdir(parents=True, exist_ok=True)\n"
        f"  (bin_dir / 'python').write_text('#!/bin/sh\\nexec {real_python} \"$@\"\\n')\n"
        '  (bin_dir / \'pip\').write_text(\'#!/bin/bash\\nif [[ "$1" == "install" && "${DEPENDENCY_TEST_FAIL:-0}" == "1" ]]; then exit 1; fi\\nexit 0\\n\')\n'
        "  (bin_dir / 'python').chmod(0o755)\n"
        "  (bin_dir / 'pip').chmod(0o755)\n"
        "  (bin_dir / 'gunicorn').write_text(f'#!{bin_dir / \"python\"}\\nprint(\"gunicorn launched\")\\n')\n"
        "  (bin_dir / 'gunicorn').chmod(0o755)\n"
        "else:\n"
        "  os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    python3.chmod(0o755)

    if activation_fails:
        mv = fake_bin / "mv"
        mv.write_text(
            "#!/bin/bash\n" 'if [[ "$1" == "-Tf" ]]; then exit 1; fi\n' 'exec /bin/mv "$@"\n',
            encoding="utf-8",
        )
        mv.chmod(0o755)

    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "-n" && "$2" == "-l" ]]; then\n'
        '  echo "systemctl restart knxohui.service is permitted"\n  exit 0\nfi\n'
        'if [[ "$*" == *provision-yaml* ]]; then exit 0; fi\n'
        'if [[ "$1" == "systemctl" && "$2" == "restart" ]]; then\n'
        '  count=0; [[ -f "$UPDATE_TEST_STATE/restarts" ]] && count=$(<"$UPDATE_TEST_STATE/restarts")\n'
        '  echo $((count + 1)) > "$UPDATE_TEST_STATE/restarts"\n'
        '  touch "$UPDATE_TEST_STATE/active"; exit 0\nfi\n'
        'if [[ "$1" == "systemctl" && "$2" == "is-active" ]]; then\n'
        '  [[ -f "$UPDATE_TEST_STATE/active" ]] && exit 0 || exit 3\nfi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)

    log_file = tmp_path / "update.log"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
            "UPDATE_TEST_STATE": str(state),
            "DEPENDENCY_TEST_FAIL": "1" if dependency_fails else "0",
            "INSTALL_DIR": str(install),
            "KNXOH_INSTALL_DIR": str(install),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "LOG_FILE": str(log_file),
            "RELEASE_TAG": "v1.2.0",
            "RELEASE_COMMIT_HASH": "c" * 40,
            "RELEASE_COMMIT_DATE": "2026-11-03T00:00:00Z",
            "RELEASE_COMMIT_MESSAGE": "Candidate release",
            "RELEASE_AUTHOR": "Release Bot",
            "KNXOH_GITHUB_REPOSITORY": "diddip21/knx_to_openhab",
        }
    )
    try:
        result = subprocess.run(
            ["bash", str(ROOT / "update.sh")],
            cwd=install,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()

    assert log_file.exists(), result.stdout + result.stderr
    log = log_file.read_text(encoding="utf-8")
    assert result.returncode == (
        1 if health_check_fails or activation_fails or dependency_fails else 0
    ), (result.stdout + result.stderr)
    assert (install / "config.json").read_text(encoding="utf-8") == (
        '{"general":{"legacy":"custom"}}'
    )
    assert (data_dir / "jobs/user.json").read_text(encoding="utf-8") == "preserved"
    assert not stale_staging.exists()
    if dependency_fails:
        assert (install / "current").is_symlink()
        assert (install / "current").resolve() == install / "releases/old-release"
        assert (install / "current/release-marker.txt").read_text(encoding="utf-8") == (
            "previous release"
        )
        assert "Could not install dependencies for v1.2.0" in log
        assert "The active release was not changed." in log
        assert not (state / "restarts").exists()
        assert list((install / "releases").iterdir()) == [install / "releases/old-release"]
    elif activation_fails:
        assert (install / "current").is_symlink()
        assert (install / "current").resolve() == install / "releases/old-release"
        assert "Could not atomically activate release v1.2.0." in log
        assert "Unactivated release candidate removed: v1.2.0." in log
        assert not (state / "restarts").exists()
        assert list((install / "releases").iterdir()) == [install / "releases/old-release"]
    elif health_check_fails:
        assert not (install / "current").exists()
        assert (state / "restarts").read_text(encoding="utf-8").strip() == "2"
        assert "The updated service did not pass its health check." in log
        assert "Previous release restored and health check passed." in log
        assert "Rejected release candidate removed: v1.2.0." in log
        assert list((install / "releases").iterdir()) == []
    else:
        assert (install / "current").is_symlink()
        active_release = (install / "current").resolve()
        assert (active_release / "version.json").is_file()
        assert (state / "restarts").read_text(encoding="utf-8").strip() == "1"
        assert "Service health check passed for v1.2.0." in log
        assert "Removed obsolete release environment: old-release." in log
        assert list((install / "releases").iterdir()) == [active_release]
        launcher_result = subprocess.run(
            [str(active_release / "venv/bin/gunicorn")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert launcher_result.returncode == 0, launcher_result.stderr
        assert launcher_result.stdout.strip() == "gunicorn launched"
    if not dependency_fails:
        assert "No release data migration is declared" in log
    archives = list(backup_dir.glob("pre-update-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], mode="r:gz") as archive:
        assert archive.extractfile("application/config.json").read() == (
            b'{"general":{"legacy":"custom"}}'
        )
        assert archive.extractfile("runtime data/jobs/user.json").read() == b"preserved"


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
