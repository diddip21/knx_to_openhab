"""Behavioral tests for setup's shared/exclusive maintenance lock."""

import grp
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from installer import write_maintenance_lock_tmpfiles as tmpfiles_module
from installer.write_maintenance_lock_tmpfiles import render_config

ROOT = Path(__file__).resolve().parents[1]
LOCK_HELPER = ROOT / "installer" / "maintenance_lock.sh"
TMPFILES_WRITER = ROOT / "installer" / "write_maintenance_lock_tmpfiles.py"


def run_lock_script(lock_file, body, *, validate_ancestors=True):
    environment = os.environ.copy()
    environment["KNXOH_MAINTENANCE_LOCK_FILE"] = str(lock_file)
    environment["KNXOH_TEST_LOCK_PATH"] = str(lock_file)
    command = 'source "$1"; shift; '
    command += (
        "resolve_maintenance_lock_path() { "
        'KNXOH_MAINTENANCE_LOCK_FILE="$KNXOH_TEST_LOCK_PATH"; '
        "export KNXOH_MAINTENANCE_LOCK_FILE; }; "
    )
    if not validate_ancestors:
        command += "_validate_maintenance_lock_ancestors() { return 0; }; "
    return subprocess.run(
        ["bash", "-c", command + body, "lock-test", str(LOCK_HELPER)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def run_lock_path_resolver(paths_file, *, override=None, policy="strict"):
    environment = os.environ.copy()
    environment["KNXOH_PATHS_FILE"] = str(paths_file)
    if override is None:
        environment.pop("KNXOH_MAINTENANCE_LOCK_FILE", None)
    else:
        environment["KNXOH_MAINTENANCE_LOCK_FILE"] = override
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; resolve_maintenance_lock_path "$2" "$3" || exit $?; '
            'printf "%s\\n" "$KNXOH_MAINTENANCE_LOCK_FILE"',
            "lock-path-test",
            str(LOCK_HELPER),
            str(paths_file),
            policy,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_runtime_lock_path_uses_saved_custom_path_when_environment_is_unset(tmp_path):
    saved_lock = "/run/lock/knxoh private/maintenance.lock"
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        "KNXOH_MAINTENANCE_LOCK_FILE='/run/lock/knxoh private/maintenance.lock'\n",
        encoding="utf-8",
    )

    result = run_lock_path_resolver(paths_file)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{saved_lock}\n"


def test_runtime_lock_path_rejects_conflicting_override(tmp_path):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(
        "KNXOH_MAINTENANCE_LOCK_FILE=/run/lock/knx_to_openhab/maintenance.lock\n",
        encoding="utf-8",
    )

    result = run_lock_path_resolver(paths_file, override="/run/lock/other/maintenance.lock")

    assert result.returncode != 0
    assert "conflicts with the persisted" in result.stderr


def test_runtime_lock_path_rejects_unpersisted_custom_override(tmp_path):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text("KNXOH_DATA_DIR=/var/lib/knx_to_openhab\n", encoding="utf-8")

    result = run_lock_path_resolver(paths_file, override="/run/lock/custom/maintenance.lock")

    assert result.returncode != 0
    assert "not persisted" in result.stderr


def test_setup_can_resolve_initial_custom_lock_path(tmp_path):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text("", encoding="utf-8")

    result = run_lock_path_resolver(
        paths_file,
        override="/run/lock/custom/maintenance.lock",
        policy="allow-initial",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "/run/lock/custom/maintenance.lock\n"


@pytest.mark.parametrize(
    "contents",
    (
        "KNXOH_MAINTENANCE_LOCK_FILE=/run/lock/one\nKNXOH_MAINTENANCE_LOCK_FILE=/run/lock/two\n",
        'KNXOH_MAINTENANCE_LOCK_FILE="unterminated\n',
        "KNXOH_MAINTENANCE_LOCK_FILE\n",
        "KNXOH_MAINTENANCE_LOCK_FILE /run/lock/custom/maintenance.lock\n",
        "KNXOH_MAINTENANCE_LOCK_FILE = /run/lock/custom/maintenance.lock\n",
        "KNXOH_MAINTENANCE_LOCK_FILE+=/run/lock/custom/maintenance.lock\n",
    ),
)
def test_runtime_lock_path_rejects_duplicate_or_malformed_saved_value(tmp_path, contents):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text(contents, encoding="utf-8")

    result = run_lock_path_resolver(paths_file)

    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower() or "malformed" in result.stderr.lower()


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_ensure_lock_creates_secure_regular_file_without_truncating_existing_inode(tmp_path):
    lock_file = tmp_path / "private lock dir" / "maintenance.lock"
    lock_file.parent.mkdir()
    lock_file.parent.chmod(0o750)
    lock_file.write_text("existing inode data", encoding="utf-8")
    original_inode = lock_file.stat().st_ino
    group_name = grp.getgrgid(os.getgid()).gr_name

    result = run_lock_script(
        lock_file,
        'ensure_maintenance_lock "$(id -gn)"',
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert lock_file.stat().st_ino == original_inode
    assert lock_file.read_text(encoding="utf-8") == "existing inode data"
    assert lock_file.stat().st_uid == 0
    assert lock_file.stat().st_mode & 0o777 == 0o660
    assert grp.getgrgid(lock_file.stat().st_gid).gr_name == group_name
    assert lock_file.parent.stat().st_uid == 0
    assert lock_file.parent.stat().st_mode & 0o777 == 0o750


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_ensure_lock_rejects_hard_link_before_changing_file_metadata(tmp_path):
    lock_dir = tmp_path / "private-lock-dir"
    lock_dir.mkdir(mode=0o750)
    lock_dir.chmod(0o750)
    unrelated_file = tmp_path / "unrelated.txt"
    unrelated_file.write_text("must remain unchanged", encoding="utf-8")
    unrelated_file.chmod(0o644)
    lock_file = lock_dir / "maintenance.lock"
    os.link(unrelated_file, lock_file)
    original_stat = unrelated_file.stat()
    group_name = grp.getgrgid(os.getgid()).gr_name

    result = run_lock_script(lock_file, f'ensure_maintenance_lock "{group_name}"')

    assert result.returncode == 2
    assert "hard link" in result.stderr
    assert unrelated_file.stat().st_ino == original_stat.st_ino
    assert unrelated_file.stat().st_nlink == 2
    assert unrelated_file.stat().st_mode & 0o777 == 0o644
    assert unrelated_file.stat().st_gid == original_stat.st_gid
    assert unrelated_file.read_text(encoding="utf-8") == "must remain unchanged"


def test_shared_and_exclusive_locks_are_mutually_exclusive_and_releaseable(tmp_path):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    result = run_lock_script(
        lock_file,
        "acquire_maintenance_exclusive_lock || exit 10; "
        'if flock --nonblock --shared "$KNXOH_MAINTENANCE_LOCK_FILE" -c true; then exit 11; '
        "else status=$?; fi; "
        '[[ "$status" == 1 ]] || exit 12; '
        "release_maintenance_lock || exit 13; "
        "acquire_maintenance_shared_lock || exit 14; "
        'if flock --nonblock --exclusive "$KNXOH_MAINTENANCE_LOCK_FILE" -c true; then exit 15; '
        "else status=$?; fi; "
        '[[ "$status" == 1 ]] || exit 16; '
        "release_maintenance_lock",
        validate_ancestors=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_lock_descriptor_remains_held_across_exec(tmp_path):
    lock_file = tmp_path / "maintenance.lock"
    lock_file.touch()
    result = run_lock_script(
        lock_file,
        "acquire_maintenance_shared_lock || exit 10; "
        'exec flock --nonblock --exclusive "$KNXOH_MAINTENANCE_LOCK_FILE" -c true',
        validate_ancestors=False,
    )

    assert result.returncode == 1


def test_systemd_tmpfiles_recreates_a_custom_lock_before_services_start(tmp_path, monkeypatch):
    lock_file = Path("/run/lock") / f"run locks {tmp_path.name}" / "maintenance.lock"
    config_file = tmp_path / "tmpfiles.d" / "knx_to_openhab.conf"
    monkeypatch.setattr(
        tmpfiles_module.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=0),
    )
    tmpfiles_module.write_config(lock_file, config_file)
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    contents = config_file.read_text(encoding="utf-8").splitlines()
    escaped_parent = str(lock_file.parent).replace(" ", "\\x20")
    assert contents == [
        f"d {escaped_parent} 0750 root knxohui -",
        f"f {escaped_parent}/maintenance.lock 0660 root knxohui -",
    ]
    assert '"$KNXOH_MAINTENANCE_LOCK_FILE"' in setup
    config_install = setup.index("write_maintenance_lock_tmpfiles.py")
    tmpfiles_create = setup.index("systemd-tmpfiles --create", config_install)
    service_start = setup.index("setup_systemctl_if_unmasked knxohui.service restart")
    assert config_install < tmpfiles_create < service_start


def test_tmpfiles_writer_escapes_literal_percent_specifiers(tmp_path, monkeypatch):
    lock_file = Path("/run/lock") / f"custom %u lock {tmp_path.name}" / "maintenance.lock"
    monkeypatch.setattr(
        tmpfiles_module.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=0),
    )

    config = render_config(lock_file)
    escaped_parent = str(lock_file.parent).replace(" ", "\\x20").replace("%", "%%")

    assert f"d {escaped_parent} 0750 root knxohui -" in config
    assert f"f {escaped_parent}/maintenance.lock 0660 root knxohui -" in config


def test_tmpfiles_writer_requires_service_group_for_missing_parent(tmp_path, monkeypatch):
    lock_file = Path("/run/lock") / f"missing-knxohui-group-{tmp_path.name}" / "maintenance.lock"

    def missing_group(_name):
        raise KeyError("knxohui")

    monkeypatch.setattr(tmpfiles_module.grp, "getgrnam", missing_group)

    with pytest.raises(ValueError, match="service group.*knxohui"):
        render_config(lock_file)


@pytest.mark.skipif(shutil.which("systemd-tmpfiles") is None, reason="systemd-tmpfiles is required")
def test_systemd_tmpfiles_creates_the_literal_percent_path(tmp_path, monkeypatch):
    lock_file = Path("/run/lock") / f"custom %u lock {tmp_path.name}" / "maintenance.lock"
    config_file = tmp_path / "tmpfiles.d" / "percent.conf"
    config_file.parent.mkdir()
    monkeypatch.setattr(
        tmpfiles_module.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=0),
    )
    config_file.write_text(
        render_config(lock_file).replace(" root knxohui ", " - - "), encoding="utf-8"
    )
    root = tmp_path / "tmpfiles-root"
    root.mkdir()

    result = subprocess.run(
        ["systemd-tmpfiles", "--create", f"--root={root}", str(config_file)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    literal_parent = root.joinpath(*lock_file.parent.parts[1:])
    assert literal_parent.is_dir()
    assert (literal_parent / "maintenance.lock").is_file()


@pytest.mark.parametrize(
    "lock_file",
    (
        Path("/tmp/maintenance.lock"),
        Path("/var/lock/maintenance.lock"),
        Path("/run/lock/maintenance.lock"),
    ),
)
def test_tmpfiles_refuses_shared_lock_parent_directories(lock_file):
    with pytest.raises(ValueError, match="dedicated"):
        render_config(lock_file)


@pytest.mark.parametrize(
    "lock_file",
    (
        Path("/var/cache/maintenance.lock"),
        Path("/var/log/maintenance.lock"),
        Path("/var/tmp/maintenance.lock"),
        Path("/usr/share/maintenance.lock"),
        Path("/run/user/maintenance.lock"),
    ),
)
def test_lock_validation_refuses_common_shared_system_directories(lock_file):
    result = run_lock_script(lock_file, "validate_maintenance_lock_location root")

    assert result.returncode == 2
    assert "dedicated" in result.stderr


def test_lock_validation_refuses_existing_non_dedicated_parent(tmp_path):
    lock_dir = tmp_path / "existing-shared-directory"
    lock_dir.mkdir(mode=0o755)
    lock_file = lock_dir / "maintenance.lock"

    result = run_lock_script(lock_file, "validate_maintenance_lock_location root")

    assert result.returncode == 2
    assert "dedicated" in result.stderr or "untrusted writable ancestor" in result.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="ancestor ownership assertions require root")
def test_lock_validation_and_acquisition_reject_untrusted_writable_ancestor(tmp_path):
    writable_ancestor = tmp_path / "writable-ancestor"
    lock_dir = writable_ancestor / "private-lock-dir"
    lock_dir.mkdir(parents=True, mode=0o750)
    writable_ancestor.chmod(0o777)
    lock_dir.chmod(0o750)
    lock_file = lock_dir / "maintenance.lock"
    lock_file.touch(mode=0o660)
    lock_file.chmod(0o660)

    validation = run_lock_script(lock_file, "validate_maintenance_lock_location root")
    acquisition = run_lock_script(lock_file, "acquire_maintenance_shared_lock")

    assert validation.returncode == 2
    assert "untrusted writable ancestor" in validation.stderr
    assert acquisition.returncode == 2
    assert "untrusted writable ancestor" in acquisition.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="ancestor ownership assertions require root")
def test_tmpfiles_writer_rejects_untrusted_writable_ancestor(tmp_path, monkeypatch):
    writable_ancestor = tmp_path / "writable-ancestor"
    lock_dir = writable_ancestor / "private-lock-dir"
    lock_dir.mkdir(parents=True, mode=0o750)
    writable_ancestor.chmod(0o777)
    lock_dir.chmod(0o750)
    monkeypatch.setattr(
        tmpfiles_module.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=0),
    )

    with pytest.raises(ValueError, match="untrusted writable ancestor"):
        render_config(lock_dir / "maintenance.lock")


def test_tmpfiles_refuses_lock_parent_inside_managed_directory(tmp_path):
    data_dir = tmp_path / "runtime"
    lock_file = data_dir / "maintenance.lock"

    with pytest.raises(ValueError, match="dedicated"):
        render_config(lock_file, managed_paths=(data_dir,))


@pytest.mark.parametrize(
    "lock_file",
    (
        Path("/var/cache/maintenance.lock"),
        Path("/var/log/maintenance.lock"),
        Path("/var/tmp/maintenance.lock"),
        Path("/usr/share/maintenance.lock"),
        Path("/run/user/maintenance.lock"),
    ),
)
def test_tmpfiles_refuses_common_shared_system_directories(lock_file):
    with pytest.raises(ValueError, match="dedicated"):
        render_config(lock_file)


def test_tmpfiles_refuses_existing_non_dedicated_parent(tmp_path):
    lock_dir = tmp_path / "existing-shared-directory"
    lock_dir.mkdir(mode=0o755)

    with pytest.raises(ValueError, match="dedicated|untrusted|service group"):
        render_config(lock_dir / "maintenance.lock")


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership assertions require root")
def test_tmpfiles_refuses_hard_link_lock_file(tmp_path, monkeypatch):
    lock_dir = tmp_path / "private-lock-dir"
    lock_dir.mkdir(mode=0o750)
    lock_dir.chmod(0o750)
    lock_file = lock_dir / "maintenance.lock"
    unrelated_file = tmp_path / "unrelated.txt"
    unrelated_file.write_text("preserve", encoding="utf-8")
    os.link(unrelated_file, lock_file)
    monkeypatch.setattr(
        tmpfiles_module.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=os.getgid()),
    )

    with pytest.raises(ValueError, match="hard links"):
        render_config(lock_file)
