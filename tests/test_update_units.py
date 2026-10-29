"""Protected updater provisioning; no live accounts, units or host policy changes."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def protected_root():
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("requires temporary root-owned Linux directories")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="knxoh-task7-", dir="/run") as scratch:
        yield Path(scratch)


def test_fixed_root_units_and_acyclic_recovery():
    for name, mode in (("update", "run"), ("update-recovery", "recover-boot")):
        unit = (ROOT / f"installer/knxohui-{name}.service").read_text()
        assert "Type=oneshot" in unit
        assert "User=root" in unit
        assert "NoNewPrivileges=yes" in unit
        assert "UMask=0077" in unit
        assert "LimitNOFILE=32768" in unit
        assert "ProtectSystem=strict" in unit
        assert "WorkingDirectory=/" in unit
        assert (
            "ExecStart=/usr/bin/python3 -I "
            "/usr/local/libexec/knx_to_openhab/update_release.py "
            f"--{mode} --paths-file /etc/knx_to_openhab/paths.env"
        ) in unit
        assert "ExecStart=+" not in unit
        assert "/current" not in unit and "/venv" not in unit
        assert "EnvironmentFile=" not in unit
        assert "PartOf=" not in unit
    recovery = (ROOT / "installer/knxohui-update-recovery.service").read_text()
    assert "RemainAfterExit=yes" in recovery
    assert "Requires=systemd-tmpfiles-setup.service" in recovery
    assert "After=systemd-tmpfiles-setup.service" in recovery
    assert "Wants=" not in recovery
    for name in (
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "knxohui-update.service",
    ):
        unit = (ROOT / "installer" / name).read_text()
        assert "Requires=knxohui-update-recovery.service" in unit
        assert "After=knxohui-update-recovery.service" in unit


def test_dropins_paths_and_complete_bundle():
    from installer.update_bootstrap import BUNDLE, render_dropins
    from installer.update_core.protocol import Paths

    paths = Paths(
        Path("/opt/my app/releases"),
        Path("/opt/my app/current"),
        Path("/etc/my app"),
        Path("/var/lib/my app"),
        Path("/var/backups/my app"),
    )
    drops = render_dropins(paths, Path("/etc/my app/paths.env"))
    assert set(drops) == {
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-update.service",
        "knxohui-update-recovery.service",
    }
    for name in ("knxohui-update.service", "knxohui-update-recovery.service"):
        text = drops[name]
        assert '--paths-file "/etc/my app/paths.env"' in text
        assert '"/opt/my app"' in text
        assert '"/etc/my app"' in text
        assert '"/var/lib/my app"' not in text  # requests are read-only
        assert '"/var/backups/my app"' not in text
        assert '"/var/lib/knxohupdate-preparation"' in text
    assert set(BUNDLE) == {
        "update_release.py",
        "update_start_guard.py",
        "update_prepare.py",
        "update_core/__init__.py",
        "update_core/protocol.py",
        "update_core/secure_fs.py",
        "update_core/state.py",
        "update_core/artifacts.py",
        "update_core/maintenance.py",
        "update_core/systemd.py",
        "update_core/transaction.py",
    }


@pytest.mark.parametrize("bad", ["$x", "%x", 'a"b', "a\\b", "a\nb", "a\x00b"])
def test_provisioning_rejects_same_path_alphabet_as_adapter(bad):
    from installer.update_bootstrap import render_dropins
    from installer.update_core.protocol import Paths

    with pytest.raises(ValueError):
        render_dropins(
            Paths(
                Path("/opt/" + bad) / "releases",
                Path("/opt/app/current"),
                Path("/etc/app"),
                Path("/var/lib/app"),
                Path("/var/backups/app"),
            ),
            Path("/etc/app/paths.env"),
        )


@pytest.mark.parametrize(
    "contract",
    [
        "/root/paths.env",
        "/tmp/paths.env",
        "/var/lib/app/paths.env",
        "/opt/app/paths.env",
        "/etc/app/config.json",
        "/etc/app/.updater-state/paths.env",
    ],
)
def test_contract_cannot_be_hidden_candidate_runtime_or_settings_file(contract):
    from installer.update_bootstrap import render_dropins
    from installer.update_core.protocol import Paths

    paths = Paths(
        Path("/opt/app/releases"),
        Path("/opt/app/current"),
        Path("/etc/app"),
        Path("/var/lib/app"),
        Path("/var/backups/app"),
    )
    with pytest.raises(ValueError):
        render_dropins(paths, Path(contract))


def test_launchers_use_actual_fixed_guard_cli_and_fail_closed():
    for script, role in (("launch_web.sh", "ui"), ("launch_backup_cleanup.sh", "cleanup")):
        text = (ROOT / "installer" / script).read_text()
        assert "/usr/bin/python3 -I" in text
        assert "/usr/local/libexec/knx_to_openhab/update_start_guard.py" in text
        for option in ("--releases", "--current", "--config-dir", f"--role {role}"):
            assert option in text
        assert "Missing protected updater startup guard" in text
        assert text.index("--role") < text.index('APP_DIR="$INSTALL_DIR/current"')


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="protected temporary Linux root fixture",
)
def test_bootstrap_refuses_pending_future_and_unsafe_state_before_writes(tmp_path):
    # Existing strict root fixtures must not live below pytest's shared /tmp parents.
    import tempfile

    from installer.update_bootstrap import check_clean_before_install
    from installer.update_core.protocol import Paths

    with tempfile.TemporaryDirectory(dir="/root") as scratch:
        root = Path(scratch)
        config = root / "config"
        config.mkdir()
        paths = Paths(
            root / "app/releases", root / "app/current", config, root / "data", root / "backup"
        )
        check_clean_before_install(paths)  # fresh/legacy: no managed layout required
        state = config / ".updater-state"
        state.mkdir(mode=0o700)
        journal = state / "journal.json"
        for raw in (b'{"format_version":999}', b'{"phase":"activated"}', b"{}"):
            journal.write_bytes(raw)
            with pytest.raises(ValueError):
                check_clean_before_install(paths)
            assert journal.read_bytes() == raw
        journal.unlink()
        (config / ".updater-maintenance.json").write_text("{}")
        with pytest.raises(ValueError):
            check_clean_before_install(paths)


def test_repair_cannot_chown_releases_to_service_or_replace_from_candidate():
    repair = (ROOT / "fix_permissions.sh").read_text()
    assert 'chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"' not in repair
    assert "verified administrator bootstrap" in repair
    install = (ROOT / "install.sh").read_text()
    assert 'run_setup_script "$INSTALL_DIR/current"' not in install
    assert 'run_setup_script "$source_dir"' not in install


def test_sudo_start_rule_exact_and_no_worker_privilege():
    policy = (ROOT / "installer/knxohui.sudoers").read_text()
    for prefix in ("/bin", "/usr/bin"):
        assert f"{prefix}/systemctl start --no-block knxohui-update.service" in policy
    assert "knxohupdate" not in policy
    assert "systemd-run" not in policy and "*" not in policy


def test_inherited_lock_is_live_exclusive_and_inode_bound(protected_root):
    from installer.update_core.state import LifecycleLock

    lock = LifecycleLock(protected_root / "host.lock")
    with lock.acquire() as fd:
        with lock.inherited(fd) as borrowed:
            assert borrowed == fd
        with pytest.raises(BlockingIOError):
            with lock.acquire():
                pytest.fail("borrower released parent's lock")
        wrong = os.open(protected_root / "other", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with pytest.raises(ValueError):
                with lock.inherited(wrong):
                    pytest.fail("substituted descriptor")
        finally:
            os.close(wrong)
    unlocked = os.open(lock.path, os.O_RDWR)
    try:
        with pytest.raises(ValueError, match="not locked"):
            with lock.inherited(unlocked):
                pytest.fail("unlocked descriptor")
    finally:
        os.close(unlocked)


def test_live_descriptor_survives_actual_nested_bash_and_isolated_python(protected_root):
    from installer.update_core.state import LifecycleLock

    lock = LifecycleLock(protected_root / "host.lock")
    script = protected_root / "nested.py"
    script.write_text(
        "import fcntl, os, stat, sys\n"
        "fd = int(sys.argv[1])\n"
        "a = os.fstat(fd); b = os.stat(sys.argv[2], follow_symlinks=False)\n"
        "assert (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)\n"
        "assert a.st_uid == 0 and stat.S_IMODE(a.st_mode) == 0o600\n"
        "other = os.open(sys.argv[2], os.O_RDONLY | os.O_NOFOLLOW)\n"
        "try:\n"
        "    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('parent lease lost')\n"
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    )
    with lock.acquire() as fd:
        result = subprocess.run(
            [
                "/bin/bash",
                "-c",
                'exec /usr/bin/python3 -I "$1" "$2" "$3"',
                "nested",
                str(script),
                str(fd),
                str(lock.path),
            ],
            pass_fds=(fd,),
            capture_output=True,
            text=True,
            check=False,
            cwd="/",
            env={"PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with pytest.raises(BlockingIOError):
            with lock.acquire():
                pytest.fail("nested command released host lease")


def test_tmpfiles_creates_boot_lock_without_replacing_live_inode(protected_root):
    tmpfiles = shutil.which("systemd-tmpfiles")
    if tmpfiles is None:
        pytest.skip("systemd-tmpfiles unavailable")
    rule = ROOT / "installer/knxohui-tmpfiles.conf"
    assert rule.is_file(), "boot must create the required writable lock leaf before namespace setup"
    raw = rule.read_bytes()
    assert b"\r" not in raw
    assert raw.decode().strip() == "f /run/lock/knxohui-lifecycle.lock 0600 root root -"
    (protected_root / "run/lock").mkdir(parents=True)
    config = protected_root / "lock.conf"
    config.write_bytes(raw)
    lock = protected_root / "run/lock/knxohui-lifecycle.lock"
    command = [tmpfiles, "--create", "--root=" + str(protected_root), str(config)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    info = lock.stat()
    assert (info.st_uid, info.st_gid, info.st_mode & 0o7777) == (0, 0, 0o600)
    lock.write_bytes(b"do-not-truncate")
    with lock.open("rb") as held:
        import fcntl

        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert (lock.stat().st_dev, lock.stat().st_ino) == (info.st_dev, info.st_ino)
        assert lock.read_bytes() == b"do-not-truncate"


def test_bootstrap_holds_host_lease_through_nested_work_and_refuses_before_writes(
    protected_root, monkeypatch
):
    from installer import update_bootstrap as admin
    from installer.update_bootstrap import installer_lease
    from installer.update_core.protocol import Paths
    from installer.update_core.state import LifecycleLock

    paths = Paths(
        protected_root / "app/releases",
        protected_root / "app/current",
        protected_root / "config",
        protected_root / "data",
        protected_root / "backup",
    )
    lock = LifecycleLock(protected_root / "host.lock")
    contract = protected_root / "paths.env"
    monkeypatch.setattr(admin, "PATHS_FILE", contract)
    with installer_lease(paths, contract, lock=lock) as fd:
        with installer_lease(paths, contract, inherited=fd, lock=lock):
            with pytest.raises(BlockingIOError):
                with lock.acquire():
                    pytest.fail("nested call lost lifecycle ownership")
        paths.config_dir.mkdir()
        (paths.config_dir / ".updater-state").mkdir(mode=0o700)
        journal = paths.config_dir / ".updater-state/journal.json"
        journal.write_text('{"format_version":999}')
        before = {p: p.read_bytes() for p in protected_root.rglob("*") if p.is_file()}
        with pytest.raises(ValueError):
            with installer_lease(paths, contract, inherited=fd, lock=lock):
                pytest.fail("future journal accepted")
        assert before == {p: p.read_bytes() for p in protected_root.rglob("*") if p.is_file()}


def test_custom_contract_cannot_bypass_pending_default_installation(protected_root, monkeypatch):
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths
    from installer.update_core.state import LifecycleLock

    original = Paths(
        protected_root / "old/releases",
        protected_root / "old/current",
        protected_root / "old-config",
        protected_root / "old-data",
        protected_root / "old-backup",
    )
    original.releases.mkdir(parents=True)
    state = original.config_dir / ".updater-state"
    state.mkdir(parents=True, mode=0o700)
    journal = state / "journal.json"
    journal.write_bytes(b'{"format_version":999}')
    canonical = protected_root / "canonical.env"
    canonical.write_text(
        "".join(
            f'{key}="{value}"\n'
            for key, value in zip(
                ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                (
                    original.releases.parent,
                    original.config_dir,
                    original.data_dir,
                    original.backup_dir,
                ),
            )
        )
    )
    monkeypatch.setattr(admin, "PATHS_FILE", canonical)
    requested = Paths(
        protected_root / "new/releases",
        protected_root / "new/current",
        protected_root / "new-config",
        protected_root / "new-data",
        protected_root / "new-backup",
    )
    with pytest.raises(ValueError):
        with admin.installer_lease(
            requested,
            protected_root / "override.env",
            lock=LifecycleLock(protected_root / "host.lock"),
        ):
            pytest.fail("alternate metadata bypassed the existing protected journal")
    assert journal.read_bytes() == b'{"format_version":999}'


def test_provisioning_retains_lease_inode_and_private_state(protected_root, monkeypatch):
    import json
    from types import SimpleNamespace

    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths

    paths = Paths(
        protected_root / "app/releases",
        protected_root / "app/current",
        protected_root / "config",
        protected_root / "data",
        protected_root / "backup",
    )
    paths.config_dir.mkdir()
    monkeypatch.setattr(admin, "PREPARATION", protected_root / "preparation")
    monkeypatch.setattr(admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_gid=65533))
    worker = SimpleNamespace(pw_gid=65534)
    admin.provision_state(paths, worker)
    lease = paths.config_dir / ".updater-mutation.lock"
    with lease.open("wb") as stream:
        stream.write(b"lease-content-must-not-be-truncated")
    before = lease.stat()
    admin.provision_state(paths, worker)
    after = lease.stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert lease.read_bytes() == b"lease-content-must-not-be-truncated"
    assert (after.st_uid, after.st_gid, after.st_mode & 0o7777) == (0, 65533, 0o660)
    private = (paths.config_dir / ".updater-state").stat()
    assert (private.st_uid, private.st_gid, private.st_mode & 0o7777) == (0, 0, 0o700)
    prep = admin.PREPARATION.stat()
    assert (prep.st_uid, prep.st_gid, prep.st_mode & 0o7777) == (0, 65534, 0o750)
    for name in (".updater-status.json", ".updater-log.txt"):
        info = (paths.config_dir / name).stat()
        assert (info.st_uid, info.st_mode & 0o7777) == (0, 0o644)
    from installer.update_core.state import PHASES

    status = json.loads((paths.config_dir / ".updater-status.json").read_bytes())
    assert status["format_version"] == 1
    assert status["phase"] in PHASES
    assert "request_id" not in status


@pytest.mark.parametrize("group", ["knxohui", "openhab", "sudo", "wheel"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX account database")
def test_worker_forbidden_supplementary_membership(group, monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=100, pw_gid=100))
    monkeypatch.setattr(admin.grp, "getgrgid", lambda gid: SimpleNamespace(gr_name=group))
    account = SimpleNamespace(pw_uid=101, pw_gid=101, pw_shell="/usr/sbin/nologin")
    with pytest.raises(ValueError, match="identity/memberships"):
        admin.check_worker(account, [101, 102])


@pytest.mark.skipif(os.name != "posix", reason="POSIX account database")
def test_worker_forbidden_gid_cannot_hide_behind_group_alias(monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=100, pw_gid=100))
    monkeypatch.setattr(
        admin.grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="innocent-alias")
    )
    monkeypatch.setattr(admin.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=102))
    with pytest.raises(ValueError):
        admin.check_worker(
            SimpleNamespace(pw_uid=101, pw_gid=101, pw_shell="/usr/sbin/nologin"), [101, 102]
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX account database")
@pytest.mark.parametrize("uid,gid", [(0, 100), (100, 0)])
def test_provisioning_refuses_root_aliased_ui_identity(uid, gid, monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=uid, pw_gid=gid))
    monkeypatch.setattr(admin.grp, "getgrgid", lambda value: SimpleNamespace(gr_name="knxohupdate"))
    monkeypatch.setattr(admin.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=500))
    with pytest.raises(ValueError):
        admin.check_worker(
            SimpleNamespace(pw_uid=101, pw_gid=101, pw_shell="/usr/sbin/nologin"), [101]
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX account database")
def test_worker_cannot_alias_openhab_uid_without_group_membership(monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(
        admin.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=100 if name == "knxohui" else 101, pw_gid=200),
    )
    monkeypatch.setattr(admin.grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="knxohupdate"))
    monkeypatch.setattr(admin.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=500))
    with pytest.raises(ValueError):
        admin.check_worker(
            SimpleNamespace(pw_uid=101, pw_gid=101, pw_shell="/usr/sbin/nologin"), [101]
        )


@pytest.mark.parametrize("shell", ["/tmp/nologin", "/tmp/false", "/bin/bash"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX account database")
def test_worker_requires_actual_nonlogin_shell_not_just_a_filename(shell, monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(admin.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=100, pw_gid=100))
    monkeypatch.setattr(admin.grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="knxohupdate"))
    with pytest.raises(ValueError):
        admin.check_worker(SimpleNamespace(pw_uid=101, pw_gid=101, pw_shell=shell), [101])


@pytest.mark.parametrize("returncode", [0, 2])
def test_worker_direct_sudo_grants_or_failed_query_are_refused(returncode, monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    calls = []

    def query(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(admin.subprocess, "run", query)
    with pytest.raises(ValueError):
        admin.check_worker_sudo()
    assert calls[0][0] == ["/usr/bin/sudo", "-n", "-l", "-U", "knxohupdate"]
    assert calls[0][1]["cwd"] == "/"


@pytest.mark.parametrize(
    "message,allowed",
    [
        ("User knxohupdate is not allowed to run sudo on test-host.\n", True),
        ("sudo: parse error in policy\n", False),
        ("", False),
    ],
)
def test_worker_sudo_exit_one_must_prove_denial(message, allowed, monkeypatch):
    from types import SimpleNamespace

    from installer import update_bootstrap as admin

    monkeypatch.setattr(
        admin.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=message),
    )
    if allowed:
        admin.check_worker_sudo()
    else:
        with pytest.raises(ValueError):
            admin.check_worker_sudo()


def test_bundle_policy_replacement_prevalidated_and_atomic(protected_root, monkeypatch):
    from installer import update_bootstrap as admin
    from installer.update_core.protocol import Paths

    # Redirect EVERY privileged destination to this temporary tree. The actual
    # atomic directory exchange and fsyncs run; no host unit/policy is touched.
    host = protected_root / "host"
    for directory in (host / "libexec", host / "systemd", host / "sudoers", host / "sbin"):
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(admin, "LIBEXEC", host / "libexec/knx_to_openhab")
    monkeypatch.setattr(admin, "SYSTEMD", host / "systemd")
    monkeypatch.setattr(admin, "POLICY", host / "sudoers/knxohui")
    monkeypatch.setattr(admin, "PACKAGE_HELPER", host / "sbin/knxohui-service-update")
    monkeypatch.setattr(admin, "TMPFILES", host / "tmpfiles.conf")
    paths = Paths(
        protected_root / "app/releases",
        protected_root / "app/current",
        protected_root / "config",
        protected_root / "data",
        protected_root / "backup",
    )
    checked = []
    monkeypatch.setattr(admin, "_run", lambda args: checked.append(args))
    admin.install_components(ROOT / "installer", paths, protected_root / "paths.env")
    assert admin.TMPFILES.read_bytes() == (ROOT / "installer/knxohui-tmpfiles.conf").read_bytes()
    assert checked[0][:2] == ["/usr/sbin/visudo", "-cf"]
    for name in (*admin.BUNDLE, *admin.HELPERS):
        assert (admin.LIBEXEC / name).read_bytes() == (ROOT / "installer" / name).read_bytes()
    before = {p: p.read_bytes() for p in host.rglob("*") if p.is_file()}
    admin.POLICY.chmod(0o666)
    with pytest.raises(ValueError):
        admin.install_components(ROOT / "installer", paths, protected_root / "paths.env")
    assert before == {p: p.read_bytes() for p in host.rglob("*") if p.is_file()}
    admin.POLICY.chmod(0o440)
    old_inode = admin.LIBEXEC.stat().st_ino
    admin.install_components(ROOT / "installer", paths, protected_root / "paths.env")
    assert admin.LIBEXEC.stat().st_ino != old_inode
    previous = list(admin.LIBEXEC.parent.glob(".knxohui-bundle-*"))
    assert len(previous) == 1
    assert previous[0].stat().st_ino == old_inode
    assert previous[0].stat().st_mode & 0o7777 == 0o700


def test_runtime_loader_refuses_bundle_exchange_mid_import(protected_root):
    from installer.update_bootstrap import BUNDLE

    first, replacement = protected_root / "bundle", protected_root / "replacement"
    for folder in (first, replacement):
        for name in BUNDLE:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / "installer" / name).read_bytes())
            path.chmod(0o644)
    probe = protected_root / "probe.py"
    probe.write_text(
        "import importlib.util, os, sys\n"
        "from pathlib import Path\n"
        "base = Path(sys.argv[1]); replacement = Path(sys.argv[2])\n"
        "spec = importlib.util.spec_from_file_location('guard', base / 'update_start_guard.py')\n"
        "guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)\n"
        "real_open = os.open; swapped = False\n"
        "def exchange(name, *args, **kwargs):\n"
        "    global swapped\n"
        "    if name == 'protocol.py' and not swapped:\n"
        "        swapped = True\n"
        "        os.rename(base, base.with_name('previous'))\n"
        "        os.rename(replacement, base)\n"
        "    return real_open(name, *args, **kwargs)\n"
        "os.open = exchange\n"
        "try:\n"
        "    guard._trusted_core()\n"
        "except ValueError:\n"
        "    assert swapped\n"
        "else:\n"
        "    raise AssertionError('mixed bundle import accepted')\n"
    )
    result = subprocess.run(
        ["/usr/bin/python3", "-I", str(probe), str(first), str(replacement)],
        cwd="/",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ordinary_uninstall_retains_complete_recovery_chain():
    from installer.uninstall import UninstallPaths, _removal_actions

    paths = UninstallPaths(
        Path("/opt/app"), Path("/etc/app"), Path("/var/lib/app"), Path("/var/backups/app")
    )
    commands = [a.command for a in _removal_actions(paths, False)]
    assert ("sudo", "systemctl", "stop", "knxohui-update-recovery.service") in commands
    removed = [arg for command in commands if "rm" in command for arg in command[4:]]
    for retained in (
        "/opt/app",
        "/usr/local/libexec/knx_to_openhab",
        "/etc/systemd/system/knxohui-update-recovery.service",
        "/etc/systemd/system/knxohui-update.service",
    ):
        assert retained not in removed


def test_activation_starts_recovery_only_after_installer_releases_lock(protected_root):
    from installer.update_bootstrap import activate_services
    from installer.update_core.state import LifecycleLock

    lock = LifecycleLock(protected_root / "host.lock")
    calls = []

    def runner(argv):
        # Starting recovery under this lease would fail busy (and UI Requires
        # recovery). It is deliberately a separate, read-only activation phase.
        with lock.acquire():
            calls.append(argv)

    activate_services(
        {
            "mode": "install",
            "ui_start": True,
            "ui_enable": True,
            "cleanup_start": True,
            "cleanup_enable": True,
        },
        runner,
    )
    assert calls[0] == ["/usr/bin/systemctl", "daemon-reload"]
    assert calls[1] == ["/usr/bin/systemctl", "start", "knxohui-update-recovery.service"]
    assert calls.index(["/usr/bin/systemctl", "restart", "knxohui.service"]) > 1


@pytest.mark.parametrize("marker", ["current", "base", "config"])
def test_same_boot_launcher_refuses_incomplete_administrator_pair(protected_root, marker):
    from installer.update_core.protocol import Paths
    from installer.update_core.state import check_start_allowed

    releases = protected_root / "app/releases"
    target = releases / "1.0.0"
    target.mkdir(parents=True)
    config = protected_root / "config"
    config.mkdir()
    current = protected_root / "app/current"
    current.symlink_to(target)
    paths = Paths(releases, current, config)
    assert check_start_allowed(paths, "ui")
    location = {
        "current": target / ".install-incomplete",
        "base": releases.parent / ".installer-incomplete",
        "config": config / ".installer-incomplete",
    }[marker]
    location.write_bytes(b"")
    assert not check_start_allowed(paths, "ui")
    assert not check_start_allowed(paths, "cleanup")


def test_installer_disk_finalization_precedes_unlocked_activation():
    setup = (ROOT / "installer/setup.sh").read_text()
    assert "KNXOH_BOOTSTRAP_OUTCOME" in setup
    assert "finish_protected_stage" in setup
    bootstrap = (ROOT / "installer/update_bootstrap.py").read_text()
    assert "activate_services(outcome" in bootstrap
    assert "assert_unchanged" in bootstrap


@pytest.mark.parametrize("was_incomplete", [False, True])
def test_protected_stage_serializes_relative_current_link_as_canonical_target(
    protected_root, was_incomplete
):
    from installer.update_bootstrap import read_outcome
    from installer.update_core.protocol import Paths

    release = protected_root / "app/releases/1.0.0"
    release.mkdir(parents=True)
    outcome = protected_root / "outcome.json"
    text = (ROOT / "installer/setup.sh").read_text()
    start = text.index("finish_protected_stage() {")
    end = text.index("# Package mutations", start)
    # Exercise only this source function against temporary paths; no systemd,
    # sudo, account operation or full installer is executed by this fixture.
    script = protected_root / "serialize.sh"
    script.write_text(text[start:end] + "\nfinish_protected_stage repair 0 0 0 0\n")
    env = {
        "PATH": "/usr/bin:/bin",
        "BASE": str(protected_root / "app"),
        "KNXOH_BOOTSTRAP_OUTCOME": str(outcome),
        "CURRENT_TARGET": "releases/1.0.0",
        "RELEASE_DIR": str(release),
        "RELEASE_WAS_INCOMPLETE": "1" if was_incomplete else "0",
        "MIGRATION_SNAPSHOT_PATH_FILE": "",
    }
    env.update(
        {
            name: "0"
            for name in (
                "UI_WAS_ACTIVE",
                "UI_WAS_ENABLED",
                "CLEANUP_SERVICE_WAS_ACTIVE",
                "CLEANUP_TIMER_WAS_ACTIVE",
                "CLEANUP_TIMER_WAS_ENABLED",
            )
        }
    )
    result = subprocess.run(
        ["/bin/bash", str(script)], env=env, cwd="/", capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = read_outcome(
        outcome,
        Paths(
            release.parent,
            release.parent.parent / "current",
            protected_root / "config",
            protected_root / "data",
            protected_root / "backups",
        ),
    )
    assert value["previous"] == str(release)
    assert value["release_was_incomplete"] is was_incomplete


def test_administrator_venv_uses_final_path_and_copied_interpreters():
    text = (ROOT / "installer/setup.sh").read_text()
    assert 'sudo python3 -m venv --copies "$RELEASE_DIR/venv"' in text
    assert '"$STAGING_DIR/venv/bin/pip"' not in text
    assert text.index('sudo mv "$STAGING_DIR" "$RELEASE_DIR"') < text.index(
        'sudo python3 -m venv --copies "$RELEASE_DIR/venv"'
    )
    assert 'if link.is_symlink() and os.readlink(link) == "lib":' in text


@pytest.mark.parametrize("fail_activation", [False, True, "superseded", "preparation"])
def test_actual_bootstrap_envelope_never_recurses_recovery_lock_or_restores_stale_pair(
    protected_root, monkeypatch, fail_activation
):
    import json
    import subprocess
    from types import SimpleNamespace

    from installer import update_bootstrap as admin
    from installer.config_migrations import create_snapshot
    from installer.update_core.protocol import Paths
    from installer.update_core.state import LifecycleLock

    paths = Paths(
        protected_root / "app/releases",
        protected_root / "app/current",
        protected_root / "config",
        protected_root / "data",
        protected_root / "backup",
    )
    for path in (paths.releases, paths.config_dir, paths.data_dir, paths.backup_dir):
        path.mkdir(parents=True)
    old, new = paths.releases / "1.0.0", paths.releases / "1.1.0"
    old.mkdir()
    new.mkdir()
    paths.current.symlink_to(old)
    config = paths.config_dir / "config.json"
    config.write_bytes(b'{"original":true}\n')
    config.chmod(0o640)
    contract = protected_root / "paths.env"
    contract.write_text(
        "".join(
            f'{key}="{value}"\n'
            for key, value in zip(
                ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir),
            )
        )
    )
    snapshot = create_snapshot([config], paths.config_dir / ".installer-state")
    marker = new / ".migration-snapshot-path"
    marker.write_text(str(snapshot))
    lock = LifecycleLock(protected_root / "host.lock")
    monkeypatch.setattr(admin, "LifecycleLock", lambda: lock)
    monkeypatch.setattr(admin, "PATHS_FILE", contract)
    calls = []

    def fake_shell(argv, **kwargs):
        assert argv[0] == "/bin/bash"
        assert kwargs["cwd"] == "/"
        assert "PYTHONPATH" not in kwargs["env"]
        assert "VIRTUAL_ENV" not in kwargs["env"]
        fd = int(kwargs["env"]["KNXOH_LIFECYCLE_FD"])
        with lock.inherited(fd):
            with pytest.raises(BlockingIOError):
                with lock.acquire():
                    pytest.fail("disk writes outside lease")
            config.write_bytes(b'{"migrated":true}\n')
            paths.current.unlink()
            paths.current.symlink_to(new)
            value = {
                key: False
                for key in (
                    "ui_was_active",
                    "ui_was_enabled",
                    "cleanup_service_was_active",
                    "cleanup_timer_was_active",
                    "cleanup_timer_was_enabled",
                )
            }
            value.update(
                mode="install",
                release=str(new),
                previous=str(old),
                snapshot_file=str(marker),
                release_was_incomplete=False,
                ui_start=True,
                ui_enable=True,
                cleanup_start=True,
                cleanup_enable=True,
            )
            if fail_activation == "preparation":
                # Shell trap restores disk state under the inherited lease and
                # delegates ONLY service-state restoration to the parent.
                value["mode"] = "failed"
                config.write_bytes(b'{"original":true}\n')
                paths.current.unlink()
                paths.current.symlink_to(old)
            Path(kwargs["env"]["KNXOH_BOOTSTRAP_OUTCOME"]).write_text(json.dumps(value))
        return SimpleNamespace(returncode=1 if fail_activation == "preparation" else 0)

    def services(argv):
        calls.append(argv)
        if "--cleanup-legacy" in argv:
            with pytest.raises(BlockingIOError):
                with lock.acquire():
                    pytest.fail("legacy cleanup lost its rechecked lifecycle lease")
            assert argv[0] == str(new / "venv/bin/python")
            assert argv[1:3] == ["-I", str(ROOT / "installer/migrate_runtime_data.py")]
            return  # existing migration cleanup has separate shell regression coverage
        if argv[0] == "/usr/bin/python3":
            # Trusted administrator snapshot restore, never candidate code.
            from installer.config_migrations import restore_snapshot

            assert argv[2] == str(ROOT / "installer/config_migrations.py")
            restore_snapshot(snapshot)
            return
        if len(argv) > 1 and argv[1] == "stop":
            # Rollback file mutations require both a lease and a deny gate.
            if (paths.config_dir / ".updater-startup-gate.json").exists():
                with pytest.raises(BlockingIOError):
                    with lock.acquire():
                        pytest.fail("rollback without lock")
            else:
                with lock.acquire():
                    pass  # restoring inactive units after the mutation phase
            return
        with lock.acquire():
            if argv[1:3] == ["restart", "knxohui.service"] and fail_activation:
                if fail_activation == "superseded":
                    config.write_bytes(b'{"new-administrator":true}\n')
                raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(admin.subprocess, "run", fake_shell)
    monkeypatch.setattr(admin, "_run", services)
    if fail_activation == "preparation":
        assert admin.execute_setup(ROOT / "installer", paths, contract, []) == 1
    elif fail_activation:
        with pytest.raises(
            ValueError,
            match="superseded" if fail_activation == "superseded" else "prior pair restored",
        ):
            admin.execute_setup(ROOT / "installer", paths, contract, [])
    else:
        assert admin.execute_setup(ROOT / "installer", paths, contract, []) == 0
    if fail_activation is True or fail_activation == "preparation":
        assert config.read_bytes() == b'{"original":true}\n'
        assert paths.current.resolve() == old
        assert not (paths.config_dir / ".updater-startup-gate.json").exists()
    elif fail_activation == "superseded":
        assert config.read_bytes() == b'{"new-administrator":true}\n'
        assert paths.current.resolve() == new
        assert not any(argv[1:2] == ["stop"] for argv in calls)
    else:
        assert paths.current.resolve() == new
        assert any("--cleanup-legacy" in argv for argv in calls)
        assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="Linux systemd static validator")
def test_rendered_custom_space_units_pass_systemd_static_validation(tmp_path):
    from installer.update_bootstrap import render_dropins
    from installer.update_core.protocol import Paths

    analyze = shutil.which("systemd-analyze")
    if analyze is None:
        pytest.skip("systemd-analyze unavailable")
    paths = Paths(
        Path("/opt/my app/releases"),
        Path("/opt/my app/current"),
        Path("/etc/my app"),
        Path("/var/lib/my app"),
        Path("/var/backups/my app"),
    )
    dropins = render_dropins(paths, Path("/etc/my app/paths.env"))
    units = []
    for name in (
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "knxohui-update.service",
        "knxohui-update-recovery.service",
    ):
        raw = (ROOT / "installer" / name).read_bytes()
        assert b"\r" not in raw, "Shipped unit must be LF, not silently normalized"
        # Validate graph/properties/quoting WITHOUT installing anything. The two
        # absent host launchers alone become /bin/true in these disposable copies;
        # their real fixed argv and guards are separately asserted above.
        raw = raw.replace(b"/usr/local/libexec/knx_to_openhab/launch_web.sh", b"/bin/true")
        raw = raw.replace(
            b"/usr/local/libexec/knx_to_openhab/launch_backup_cleanup.sh", b"/bin/true"
        )
        unit = tmp_path / name
        unit.write_bytes(raw)
        unit.chmod(0o644)
        units.append(str(unit))
        if name in dropins:
            folder = tmp_path / (name + ".d")
            folder.mkdir()
            drop = folder / "50-knxohui-paths.conf"
            drop.write_text(dropins[name])
            drop.chmod(0o644)
    result = subprocess.run(
        [analyze, "verify", "--man=no", *units], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
