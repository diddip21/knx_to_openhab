"""Final-review composition regressions; no live manager or mount operations."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from installer.update_core import secure_fs as fs
from tests.test_release_updater import installation  # noqa: F401
from tests.test_update_recovery import Crash


def sandbox_mount_ids(monkeypatch, roots):
    """Model self-bind mounts, including files, without mounting anything."""
    real = fs._mount_id

    def mount_id(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        for index, root in reversed(list(enumerate(roots))):
            if path == root or root in path.parents:
                return 100000 + index
        return real(fd)

    monkeypatch.setattr(fs, "_mount_id", mount_id)


def test_sandbox_mount_roots_lock_layout_recovery_update(installation, monkeypatch):
    updater, paths, adapter, _ = installation
    # Initially absent lock: tmpfiles creates this endpoint before unit namespace.
    updater.lock_path.touch(mode=0o600)
    sandbox_mount_ids(
        monkeypatch,
        [paths.releases.parent, paths.config_dir, updater.workspace_root, updater.lock_path],
    )
    adapter.active = dict.fromkeys(adapter.active, False)
    assert updater.recover("boot").status == "clean"
    adapter.active = dict.fromkeys(adapter.active, True)
    result = updater.run()
    assert result.status == "updated", result


def test_nested_mount_below_config_anchor_rejected(installation, monkeypatch):
    updater, paths, adapter, _ = installation
    nested = paths.config_dir / ".updater-state"
    nested.mkdir(mode=0o700)
    sandbox_mount_ids(monkeypatch, [paths.config_dir, nested])
    assert updater.run().status == "blocked"
    assert not adapter.events


@pytest.mark.parametrize("stage", ["metadata", "dependencies"])
def test_nested_child_output_mount_rejected(installation, monkeypatch, stage):
    updater, paths, adapter, _ = installation
    run_child = adapter.run_child

    def mounted_output(step, contract, workspace, candidate):
        run_child(step, contract, workspace, candidate)
        if step == stage:
            nested = workspace / "output" if stage == "metadata" else candidate / "venv"
            sandbox_mount_ids(monkeypatch, [paths.config_dir, updater.workspace_root, nested])

    adapter.run_child = mounted_output
    result = updater.run()
    assert result.status in ("failed", "blocked"), result
    assert paths.current.resolve().name == "1.0.0"


def test_anchor_identity_and_mount_pinned(installation, monkeypatch):
    from installer.update_core.state import _directory

    _, paths, _, _ = installation
    with fs.mount_anchors([paths.config_dir]):
        _directory(paths.config_dir)
        paths.config_dir.rename(paths.config_dir.with_name("old-config"))
        paths.config_dir.mkdir()
        with pytest.raises(ValueError, match="anchor changed"):
            _directory(paths.config_dir)


def crash_at(updater, monkeypatch, label):
    def boundary(actual):
        if actual == label:
            raise Crash(label)

    with monkeypatch.context() as patch:
        patch.setattr(updater, "_boundary", boundary)
        with pytest.raises(Crash):
            updater.run()
    # Model power-off before boot: writers are inactive, not stopped by recovery.
    updater.systemd.active = dict.fromkeys(updater.systemd.active, False)


@pytest.mark.parametrize("label", ["intent:committed", "effect:activate", "intent:rolled-back"])
def test_recovery_reconciles_status_then_real_demoted_submitter_claims(
    installation, monkeypatch, label
):
    from installer.update_core.state import StateStore
    from web_ui.backend.updater import Updater

    updater, paths, adapter, old_id = installation
    if label == "intent:rolled-back":
        adapter.version = "1.0.0"
    crash_at(updater, monkeypatch, label)
    assert updater.recover("boot").status in ("clean", "recovered")
    public = json.loads((paths.config_dir / ".updater-status.json").read_bytes())
    assert public["phase"] in ("committed", "rolled-back")
    assert public["request_id"] == old_id
    # Real facade maps this to a terminal outcome understood by existing JS.
    facade = object.__new__(Updater)
    facade._paths = lambda: paths
    assert facade.get_update_status()["outcome"] in ("updated", "failed", "no-update")
    assert updater.recover("boot").status in ("clean", "recovered")
    adapter.active["knxohui.service"] = True  # boot start job completes outside recovery
    adapter.version = "1.0.0" if label != "intent:committed" else "2.0.0"
    source = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(source / "tests/integration/update_fixture_process.py"),
        "submit",
        str(source),
        json.dumps(
            [
                str(p)
                for p in (
                    paths.releases,
                    paths.current,
                    paths.config_dir,
                    paths.data_dir,
                    paths.backup_dir,
                )
            ]
        ),
    ]
    child = subprocess.Popen(
        command,
        user=65533,
        group=65533,
        extra_groups=[],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not (paths.data_dir / "submission-started").exists():
            assert child.poll() is None, child.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        result = updater.run()
        assert result.status == "no-update", result
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        submitted = json.loads(stdout)
        assert submitted["status"] == "submitted"
        assert submitted["request_id"] != old_id
        journal = StateStore(paths).load()
        assert journal.request_id == submitted["request_id"]
        assert old_id in json.loads(StateStore(paths).journal_path.read_bytes())["seen_request_ids"]
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate()


@pytest.mark.parametrize("leaf", [".updater-status.json", ".updater-log.txt"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("label", ["intent:committed", "effect:activate", "intent:rolled-back"])
def test_projection_failure_retry_does_not_skip_coherent_reconciliation(
    installation, monkeypatch, leaf, after, label
):
    updater, paths, adapter, request_id = installation
    if label == "intent:rolled-back":
        adapter.version = "1.0.0"
    crash_at(updater, monkeypatch, label)
    real_write = fs.atomic_write

    def fail(path, *args):
        if path.name == leaf:
            if after:
                real_write(path, *args)
            raise OSError("projection/fsync failed")
        return real_write(path, *args)

    with monkeypatch.context() as patch:
        patch.setattr(fs, "atomic_write", fail)
        assert updater.recover("boot").status == "blocked"
    assert updater.recover("boot").status in ("clean", "recovered")
    status = json.loads((paths.config_dir / ".updater-status.json").read_bytes())
    expected = "committed" if label == "intent:committed" else "rolled-back"
    assert status["phase"] == expected and status["request_id"] == request_id
    assert (paths.config_dir / ".updater-log.txt").read_text().startswith(expected + ":")


@pytest.mark.parametrize("label", ["effect:config", "effect:activate", "intent:committed"])
@pytest.mark.parametrize("inactive_cleanup", [False, True])
def test_boot_recovery_preserves_original_pending_writer_jobs(
    installation, monkeypatch, label, inactive_cleanup
):
    updater, paths, adapter, _ = installation
    if inactive_cleanup:
        adapter.active["knxohui-backup-cleanup.service"] = False
        adapter.active["knxohui-backup-cleanup.timer"] = False
    crash_at(updater, monkeypatch, label)
    adapter.active = dict.fromkeys(adapter.active, False)
    pending = set(adapter.active)
    service = adapter.service

    def job_manager(action, name):
        if action in ("stop", "start"):
            pending.discard(name)  # real stop replaces an already queued start
        return service(action, name)

    adapter.service = job_manager
    adapter.events.clear()
    assert updater.recover("boot").status in ("clean", "recovered")
    assert pending == set(adapter.active)
    assert not any(isinstance(event, tuple) for event in adapter.events)


def test_boot_recovery_refuses_active_writer_before_disk_mutation(installation, monkeypatch):
    updater, paths, adapter, _ = installation
    crash_at(updater, monkeypatch, "effect:activate")
    adapter.active["knxohui.service"] = True
    before = (paths.config_dir / "config.json").read_bytes()
    adapter.events.clear()
    assert updater.recover("boot").status == "blocked"
    assert paths.current.resolve().name == "2.0.0"
    assert (paths.config_dir / "config.json").read_bytes() == before
    assert not adapter.events


def test_password_root_writer_never_enters_worker_environment(installation):
    import shutil

    from web_ui.backend.auth import hash_password, verify_password

    _, paths, _, _ = installation
    candidate = paths.current.resolve()
    sentinel = paths.config_dir / "POISON-EXECUTED"
    poison = f"open({str(sentinel)!r}, 'w').write('unsafe')"
    (candidate / "venv/bin").mkdir(parents=True)
    (candidate / "venv/lib/python3.12/site-packages").mkdir(parents=True)
    (candidate / "venv/bin/python").write_text("#!/usr/bin/python3\n" + poison)
    (candidate / "venv/bin/python").chmod(0o755)
    (candidate / "venv/lib/python3.12/site-packages/poison.pth").write_text("import os; " + poison)
    for name in ("sitecustomize.py", "argon2.py"):
        (candidate / name).write_text(poison)
    bundle = paths.config_dir.parent / "libexec"
    bundle.mkdir()
    helper = bundle / "set_ui_password.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "installer/set_ui_password.py", helper)
    helper.chmod(0o644)
    secrets = paths.config_dir / "secrets.env"
    secrets.write_text("SIBLING=unchanged\nKNXOH_UI_PASSWORD_B64=old\n")
    contract = paths.config_dir / "paths.env"
    contract.write_text(f'KNXOH_CONFIG_DIR="{paths.config_dir}"\n')
    password_hash = hash_password("new pässword 2026")  # trusted test dependency, not candidate
    result = subprocess.run(
        ["/usr/bin/python3", "-I", str(helper), "--hash-stdin", "--paths-file", str(contract)],
        input=password_hash + "\n",
        text=True,
        capture_output=True,
        cwd=candidate,
        env={"PYTHONPATH": str(candidate), "VIRTUAL_ENV": str(candidate / "venv")},
    )
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()
    import base64

    lines = secrets.read_text().splitlines()
    assert lines[0] == "SIBLING=unchanged"
    stored = base64.b64decode(lines[1].split("=", 1)[1]).decode()
    assert verify_password(stored, "new pässword 2026")
    assert "KNXOH_UI_PASSWORD_B64=" not in secrets.read_text()
    info = secrets.stat()
    assert (info.st_uid, info.st_gid, info.st_mode & 0o777) == (0, 65533, 0o640)
    assert "sudo systemctl restart knxohui.service" in result.stdout


@pytest.mark.parametrize("value", ["", "$(touch /bad)", "$argon2id$v=19$m=999999,t=3,p=2$bad$bad"])
def test_privileged_password_writer_accepts_only_strict_hash_data(installation, value):
    _, paths, _, _ = installation
    script = Path(__file__).resolve().parents[1] / "installer/set_ui_password.py"
    secrets = paths.config_dir / "secrets.env"
    before = secrets.read_bytes()
    result = subprocess.run(
        ["/usr/bin/python3", "-I", str(script), "--hash-stdin", "--secrets-file", str(secrets)],
        input=value,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert secrets.read_bytes() == before


def test_unprivileged_password_hash_mode_and_root_refusal(installation):
    from web_ui.backend.auth import verify_password

    _, paths, _, _ = installation
    script = Path(__file__).resolve().parents[1] / "installer/set_ui_password.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--hash-only"],
        user=65533,
        group=65533,
        extra_groups=[],
        input="new password 2026\nnew password 2026\n",
        capture_output=True,
        text=True,
        start_new_session=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert verify_password(result.stdout.strip(), "new password 2026")
    denied = subprocess.run(
        ["/usr/bin/python3", "-I", str(script), "--hash-only"],
        capture_output=True,
        text=True,
    )
    assert denied.returncode != 0 and "Never hash" in denied.stderr


@pytest.mark.parametrize("unsafe", ["symlink", "writable", "ancestor"])
def test_password_writer_refuses_unsafe_destination(installation, unsafe):
    from installer.set_ui_password import write_password_hash
    from web_ui.backend.auth import hash_password

    _, paths, _, _ = installation
    secrets = paths.config_dir / "secrets.env"
    if unsafe == "symlink":
        secrets.rename(paths.config_dir / "original")
        secrets.symlink_to(paths.config_dir / "original")
    elif unsafe == "writable":
        secrets.chmod(0o666)
    else:
        paths.config_dir.chmod(0o777)
    try:
        with pytest.raises((ValueError, OSError)):
            write_password_hash(secrets, hash_password("new password 2026"))
        assert secrets.read_bytes() == b"secret sentinel\n"
    finally:
        paths.config_dir.chmod(0o755)


def predecessor_venv(paths):
    current = paths.current.resolve()
    subprocess.run(
        ["/usr/bin/python3", "-m", "venv", "--without-pip", str(current / "venv")], check=True
    )
    assert (current / "venv/bin/python3").is_symlink()
    assert (current / "venv/lib64").is_symlink()
    return current


def test_predecessor_venv_has_actionable_nonrepair_loop_diagnostic(installation):
    updater, paths, adapter, _ = installation
    predecessor_venv(paths)
    result = updater.run()
    assert result.status == "blocked"
    assert "genuinely new verified release" in result.error
    assert "same-version" in result.error and "cannot convert" in result.error
    assert not adapter.events


def test_admin_same_version_repair_warns_inactive_activation_refuses(installation, capsys):
    from installer.update_bootstrap import check_existing_release

    _, paths, _, _ = installation
    old = predecessor_venv(paths)
    before = os.readlink(paths.current)
    assert not check_existing_release(paths, old, activating=False)
    assert "cannot convert" in capsys.readouterr().err
    inactive = paths.releases / "0.9.0"
    inactive.mkdir()
    (inactive / "VERSION").write_text("0.9.0\n")
    subprocess.run(
        ["/usr/bin/python3", "-m", "venv", "--without-pip", str(inactive / "venv")], check=True
    )
    with pytest.raises(ValueError, match="genuinely new verified release"):
        check_existing_release(paths, inactive, activating=True)
    assert os.readlink(paths.current) == before


def test_admin_new_copy_release_transition_then_later_worker_update(installation, monkeypatch):
    from installer import update_bootstrap as admin
    from installer.update_core.state import LifecycleLock
    from tests.test_release_updater import assert_sentinels

    updater, paths, adapter, _ = installation
    old = predecessor_venv(paths)
    config = (paths.config_dir / "config.json").read_bytes()
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
    source = Path(__file__).resolve().parents[1] / "installer"
    real_run = subprocess.run
    new = paths.releases / "2.0.0"

    def safe_admin_setup(argv, **kwargs):
        # Inject administrative setup effects, NOT candidate execution or host setup.
        assert argv[:2] == ["/bin/bash", str(source / "setup.sh")]
        assert "--repair" not in argv
        assert not new.exists()
        new.mkdir()
        (new / "VERSION").write_text("2.0.0\n")
        real_run(
            ["/usr/bin/python3", "-m", "venv", "--copies", "--without-pip", str(new / "venv")],
            check=True,
        )
        (new / "venv/lib64").unlink()  # exact administrator-created CPython alias only
        assert admin.check_existing_release(paths, new, activating=True)
        temporary = paths.current.with_name("admin-current")
        temporary.symlink_to(new)
        temporary.replace(paths.current)
        outcome = dict.fromkeys(
            (
                "ui_start",
                "ui_enable",
                "cleanup_start",
                "cleanup_enable",
                "ui_was_active",
                "ui_was_enabled",
                "cleanup_service_was_active",
                "cleanup_timer_was_active",
                "cleanup_timer_was_enabled",
                "release_was_incomplete",
            ),
            False,
        )
        outcome.update(
            mode="install",
            release=str(new),
            previous=str(old),
            snapshot_file=str(new / ".migration-snapshot-path"),
        )
        Path(kwargs["env"]["KNXOH_BOOTSTRAP_OUTCOME"]).write_text(json.dumps(outcome))
        return subprocess.CompletedProcess(argv, 0)

    with monkeypatch.context() as patch:
        patch.setattr(admin, "PATHS_FILE", contract)
        patch.setattr(admin, "LifecycleLock", lambda: LifecycleLock(updater.lock_path))
        patch.setattr(admin.subprocess, "run", safe_admin_setup)
        patch.setattr(admin, "_run", lambda argv: None)  # fixed service/legacy-cleanup boundary
        assert admin.execute_setup(source, paths, contract, []) == 0
    assert (old / "venv/bin/python3").is_symlink()  # old immutable environment not rewritten
    assert (paths.config_dir / "config.json").read_bytes() == config
    assert_sentinels(paths)
    adapter.version = "3.0.0"
    result = updater.run()
    assert result.status == "updated", result
    assert paths.current.resolve().name == "3.0.0"
    assert_sentinels(paths)


@pytest.mark.parametrize("leaf", [".updater-status.json", ".updater-log.txt"])
def test_reconciliation_retries_real_projection_parent_fsync_failure(
    installation, monkeypatch, leaf
):
    updater, paths, _, _ = installation
    crash_at(updater, monkeypatch, "intent:committed")
    real_replace, real_sync = os.replace, os.fsync
    replaced = False

    def replace(src, dst, **kwargs):
        nonlocal replaced
        result = real_replace(src, dst, **kwargs)
        if dst == leaf:
            replaced = True
        return result

    def fsync(fd):
        if replaced and Path(os.readlink(f"/proc/self/fd/{fd}")) == paths.config_dir:
            raise OSError("projection parent fsync fault")
        return real_sync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace)
        patch.setattr(os, "fsync", fsync)
        assert updater.recover("boot").status == "blocked"
        assert replaced
    assert updater.recover("boot").status == "clean"
    assert (
        json.loads((paths.config_dir / ".updater-status.json").read_bytes())["phase"] == "committed"
    )
    assert (paths.config_dir / ".updater-log.txt").read_text().startswith("committed:")


def test_admin_repair_reconciles_stale_status_and_checkpoint_retry(installation, monkeypatch):
    from installer.update_core.state import StateStore

    updater, paths, adapter, old_id = installation
    crash_at(updater, monkeypatch, "intent:committed")
    assert updater.recover("boot").status == "clean"
    store = StateStore(paths)
    store.publish_status("claimed", "stale projection", old_id)
    assert store.archive_terminal_for_admin()
    assert (
        json.loads((paths.config_dir / ".updater-status.json").read_bytes())["phase"] == "committed"
    )
    evidence = list(store.root.iterdir())
    store.publish_status("claimed", "stale projection", old_id)
    assert not store.archive_terminal_for_admin()
    assert (
        json.loads((paths.config_dir / ".updater-status.json").read_bytes())["phase"] == "committed"
    )
    assert set(store.root.iterdir()) == set(evidence)
    assert old_id in store._read()[1]


def test_fresh_request_cannot_bypass_prior_readiness_verification(installation, monkeypatch):
    from uuid import uuid4

    from installer.update_core.state import StateStore
    from tests.test_release_updater import FakeSystemd

    updater, paths, adapter, old_id = installation
    crash_at(updater, monkeypatch, "effect:activate")
    assert updater.recover("boot").status == "recovered"
    fresh_id = str(uuid4())
    request_path = paths.data_dir / "update/request.json"
    FakeSystemd.write(
        request_path,
        json.dumps({"format_version": 1, "request_id": fresh_id, "channel": "stable"}).encode(),
    )
    os.chown(request_path, 65533, 65533)
    adapter.events.clear()
    assert updater.run().status == "blocked"  # previous UI has not become ready
    assert StateStore(paths).load().request_id == old_id
    assert StateStore(paths).load().phase == "recovered-awaiting-start"
    assert "metadata" not in adapter.events
    assert (
        json.loads((paths.config_dir / ".updater-status.json").read_bytes())["request_id"] == old_id
    )
    adapter.active["knxohui.service"] = True
    adapter.version = "1.0.0"
    result = updater.run()
    assert result.status == "no-update" and result.request_id == fresh_id


def test_status_consumer_retries_coordinator_atomic_replacement(installation, monkeypatch):
    from installer.update_core.state import StateStore
    from installer.update_submit import read_status

    _, paths, _, request_id = installation
    store = StateStore(paths)
    store.publish_status("claimed", "old projection", request_id)
    real_read = os.read
    replaced = False

    def atomic_replace_during_read(fd, size):
        nonlocal replaced
        raw = real_read(fd, size)
        if (
            not replaced
            and Path(os.readlink(f"/proc/self/fd/{fd}"))
            == paths.config_dir / ".updater-status.json"
        ):
            replaced = True
            store.publish_status("committed", "Release update completed", request_id)
        return raw

    monkeypatch.setattr(os, "read", atomic_replace_during_read)
    status = read_status(paths)
    assert replaced and status["phase"] == "committed"
    assert status["request_id"] == request_id


def test_status_consumer_churn_is_bounded_and_unsafe_input_still_rejected(
    installation, monkeypatch
):
    from installer.update_core.state import StateStore
    from installer.update_submit import read_status

    _, paths, _, request_id = installation
    store = StateStore(paths)
    store.publish_status("claimed", "old projection", request_id)
    real_read = os.read
    replacements = 0

    def churn(fd, size):
        nonlocal replacements
        raw = real_read(fd, size)
        if Path(os.readlink(f"/proc/self/fd/{fd}")) == paths.config_dir / ".updater-status.json":
            replacements += 1
            store.publish_status("claimed", "another complete projection", request_id)
        return raw

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", churn)
        with pytest.raises(fs.EntryChangedError):
            read_status(paths)
    assert replacements == 3
    (paths.config_dir / ".updater-status.json").chmod(0o666)
    with pytest.raises(ValueError, match="ownership or mode"):
        read_status(paths)


@pytest.mark.parametrize("activate", [False, True])
def test_real_setup_check_function_and_isolated_admin_cli(installation, activate):
    import shlex
    import shutil

    from installer.update_core.state import LifecycleLock
    from tests.test_release_updater import assert_sentinels

    updater, paths, _, _ = installation
    old = predecessor_venv(paths)
    target = old
    if activate:
        target = paths.releases / "0.9.0"
        shutil.copytree(old, target, symlinks=True)
        (target / "VERSION").write_text("0.9.0\n")
    source = Path(__file__).resolve().parents[1] / "installer"
    verified = paths.config_dir.parent / "verified-source/installer"
    verified.mkdir(parents=True)
    for name in ("update_bootstrap.py", "bootstrap_activation.py"):
        shutil.copyfile(source / name, verified / name)
    shutil.copytree(
        source / "update_core",
        verified / "update_core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    contract = paths.config_dir / "paths.env"
    values = (paths.releases.parent, paths.config_dir, paths.data_dir, paths.backup_dir)
    contract.write_text(
        "".join(
            f'{key}="{path}"\n'
            for key, path in zip(
                ("KNXOH_INSTALL_DIR", "KNXOH_CONFIG_DIR", "KNXOH_DATA_DIR", "KNXOH_BACKUP_DIR"),
                values,
            )
        )
    )
    bootstrap = verified / "update_bootstrap.py"
    bootstrap.write_text(
        bootstrap.read_text().replace(
            'PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")',
            f"PATHS_FILE = Path({str(contract)!r})",
        )
    )
    state = verified / "update_core/state.py"
    state.write_text(
        state.read_text().replace(
            'Path("/run/lock/knxohui-lifecycle.lock")', f"Path({str(updater.lock_path)!r})"
        )
    )
    raw = (source / "setup.sh").read_text()
    start = raw.index("check_repair_release() {")
    function = raw[start : raw.index("\n}\n", start) + 3]
    arguments = [
        "--base",
        str(values[0]),
        "--config-dir",
        str(values[1]),
        "--data-dir",
        str(values[2]),
        "--backup-dir",
        str(values[3]),
        "--paths-file",
        str(contract),
    ]
    shell = (
        f"REPO_ROOT={shlex.quote(str(verified.parent))}\n"
        f"BOOTSTRAP_ARGS=({shlex.join(arguments)})\n"
        + function
        + f"\ncheck_repair_release {shlex.quote(str(target))} {int(activate)}\n"
    )
    config = (paths.config_dir / "config.json").read_bytes()
    with LifecycleLock(updater.lock_path).acquire() as fd:
        result = subprocess.run(
            ["/bin/bash", "-c", shell],
            pass_fds=(fd,),
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "KNXOH_LIFECYCLE_FD": str(fd)},
            timeout=15,
        )
    assert result.returncode == (2 if activate else 0), result.stderr
    assert "cannot convert" in result.stderr
    assert paths.current.resolve() == old
    assert (paths.config_dir / "config.json").read_bytes() == config
    assert_sentinels(paths)
