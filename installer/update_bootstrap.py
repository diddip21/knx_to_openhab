"""Administrator-only provisioning, NEVER invoked by the release coordinator.

The verified bootstrap supplies this complete source tree. Isolated Python loads
only that explicit tree; no installed/current/cwd/venv import is used. The parent
holds the host lease across setup, with a checked inherited descriptor for nested
calls. No CLI option can disable locking or clean-state checks.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

if os.name == "posix":
    import grp
    import pwd
else:  # Allow portable rendering/static tests; privileged operations remain POSIX-only.
    grp = pwd = None

if __package__:
    from .bootstrap_activation import activate_services, restore_services
    from .update_core import secure_fs as fs
    from .update_core.protocol import Paths
    from .update_core.state import (
        TERMINAL,
        LifecycleLock,
        StateStore,
        _current_target,
        _directory,
        _unlink,
        write_gate,
    )
    from .update_core.systemd import _path, _quoted
    from .update_core.transaction import load_paths
else:
    # Only administrator-verified sources reach this entrypoint. Do not add a
    # release or working directory to sys.path, even during bootstrap.
    spec = importlib.util.spec_from_file_location(
        "_knxoh_admin",
        Path(__file__).parent / "update_core/__init__.py",
        submodule_search_locations=[str(Path(__file__).parent / "update_core")],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    from _knxoh_admin import secure_fs as fs
    from _knxoh_admin.protocol import Paths
    from _knxoh_admin.state import (
        TERMINAL,
        LifecycleLock,
        StateStore,
        _current_target,
        _directory,
        _unlink,
        write_gate,
    )
    from _knxoh_admin.systemd import _path, _quoted
    from _knxoh_admin.transaction import load_paths

    activation_spec = importlib.util.spec_from_file_location(
        "_knxoh_admin_activation", Path(__file__).with_name("bootstrap_activation.py")
    )
    activation = importlib.util.module_from_spec(activation_spec)
    activation_spec.loader.exec_module(activation)
    activate_services, restore_services = activation.activate_services, activation.restore_services

LIBEXEC = Path("/usr/local/libexec/knx_to_openhab")
SYSTEMD = Path("/etc/systemd/system")
POLICY = Path("/etc/sudoers.d/knxohui")
PACKAGE_HELPER = Path("/usr/local/sbin/knxohui-service-update")
PREPARATION = Path("/var/lib/knxohupdate-preparation")
PATHS_FILE = Path("/etc/knx_to_openhab/paths.env")
TMPFILES = Path("/etc/tmpfiles.d/knxohui.conf")
BUNDLE = (
    "update_release.py",
    "update_start_guard.py",
    "update_prepare.py",
    *(
        f"update_core/{name}.py"
        for name in (
            "__init__",
            "protocol",
            "secure_fs",
            "state",
            "artifacts",
            "maintenance",
            "systemd",
            "transaction",
        )
    ),
)
HELPERS = ("launch_web.sh", "launch_backup_cleanup.sh", "set_ui_password.py")
UNITS = (
    "knxohui.service",
    "knxohui-backup-cleanup.service",
    "knxohui-backup-cleanup.timer",
    "knxohui-update.service",
    "knxohui-update-recovery.service",
)


def _existing_chain(path):
    """Validate existing components without creating fresh/legacy layout."""
    fs._canonical(path)
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            break
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o7022:
            raise ValueError("Unsafe bootstrap directory")


def check_clean_before_install(paths):
    """Read-only check under the HOST lock; never construct/create StateStore."""
    config = paths.config_dir
    _existing_chain(config)
    if not config.exists():
        return
    for name in (".updater-maintenance.json", ".updater-startup-gate.json"):
        try:
            (config / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError("Unreconciled updater gate/maintenance; run installed offline recovery")
    root = config / ".updater-state"
    try:
        root.lstat()
    except FileNotFoundError:
        return
    _directory(root, private=True)
    try:
        (root / "journal.json").lstat()
    except FileNotFoundError:
        return
    # Reuse the exact strict decoder and sticky replay ledger, without __init__'s
    # mkdir. A journal without a valid managed layout fails closed as well.
    store = object.__new__(StateStore)
    store.paths, store.root, store.journal_path = paths, root, root / "journal.json"
    try:
        journal = store.load()
        if journal is None or journal.phase not in TERMINAL:
            raise ValueError("Uncommitted updater journal")
        target = journal.candidate if journal.phase == "committed" else journal.prior_target
        if _current_target(paths)[0] != target:
            raise ValueError("Terminal updater journal/current mismatch")
    except (OSError, ValueError) as error:
        raise ValueError("Updater recovery required BEFORE bootstrap replacement") from error


def render_dropins(paths, paths_file):
    for path in (
        paths.releases,
        paths.current,
        paths.config_dir,
        paths.data_dir,
        paths.backup_dir,
        paths_file,
    ):
        _path(path)
    base = paths.releases.parent
    if paths.releases != base / "releases" or paths.current != base / "current":
        raise ValueError("Invalid managed layout")
    all_paths = (
        base,
        paths.config_dir,
        paths.data_dir,
        paths.backup_dir,
        PREPARATION,
        LIBEXEC,
        SYSTEMD,
        POLICY.parent,
        PACKAGE_HELPER.parent,
    )
    for index, left in enumerate(all_paths):
        if left.parts[1] in ("home", "root", "tmp"):
            raise ValueError("Path hidden by protected service sandbox")
        for right in all_paths[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("Overlapping managed paths")
    if paths_file.parts[1] in ("home", "root", "tmp"):
        raise ValueError("Paths contract hidden by protected service sandbox")
    for forbidden in (base, paths.data_dir, paths.backup_dir, PREPARATION, LIBEXEC):
        if paths_file == forbidden or forbidden in paths_file.parents:
            raise ValueError("Paths contract must be outside candidate/runtime/preparation code")
    if paths.config_dir in paths_file.parents and paths_file != paths.config_dir / "paths.env":
        raise ValueError("Paths contract must not replace settings or private recovery state")
    # EnvironmentFile values are parsed by systemd, not a shell. The four-value
    # contract itself is parsed as DATA by the coordinator.
    env = "[Service]\nEnvironmentFile=\nEnvironmentFile=" + _quoted(paths_file) + "\n"
    result = {name: env for name in UNITS[:2]}
    for name, mode in ((UNITS[3], "run"), (UNITS[4], "recover-boot")):
        result[name] = (
            "[Service]\nExecStart=\nExecStart=/usr/bin/python3 -I "
            f"{LIBEXEC}/update_release.py --{mode} --paths-file {_quoted(paths_file)}\n"
            "ReadWritePaths=\nReadWritePaths="
            + " ".join(
                _quoted(path)
                for path in (
                    base,
                    paths.config_dir,
                    PREPARATION,
                    Path("/run/lock/knxohui-lifecycle.lock"),
                )
            )
            + "\n"
        )
    return result


def check_worker(account=None, groups=None):
    account = pwd.getpwnam("knxohupdate") if account is None else account
    groups = os.getgrouplist(account.pw_name, account.pw_gid) if groups is None else groups
    forbidden = {"knxohui", "openhab", "sudo", "wheel"}
    names = {grp.getgrgid(gid).gr_name for gid in groups}
    forbidden_gids = set()
    for name in forbidden:
        try:
            forbidden_gids.add(grp.getgrnam(name).gr_gid)
        except KeyError:
            pass
    ui = pwd.getpwnam("knxohui")
    try:
        openhab_uid = pwd.getpwnam("openhab").pw_uid
    except KeyError:
        openhab_uid = None
    if (
        ui.pw_uid == 0
        or ui.pw_gid == 0
        or account.pw_uid in (0, ui.pw_uid)
        or account.pw_uid == openhab_uid
        or account.pw_gid in (0, ui.pw_gid)
        or account.pw_shell not in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false")
        or names & forbidden
        or set(groups) & forbidden_gids
    ):
        raise ValueError("Unsafe knxohupdate identity/memberships; administrator repair required")
    return account


def check_worker_sudo():
    result = subprocess.run(
        ["/usr/bin/sudo", "-n", "-l", "-U", "knxohupdate"],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    # Exit 1 can also mean a policy/query error. Accept ONLY sudo's explicit
    # complete denial, not merely a failed query. Never log permission listings.
    if result.returncode != 1 or not re.fullmatch(
        r"User knxohupdate is not allowed to run sudo on [^\r\n]+\.\n?",
        result.stdout + result.stderr,
    ):
        raise ValueError(
            "Cannot prove knxohupdate has no direct sudo grants; repair administrator policy"
        )


def _run(argv):
    subprocess.run(
        argv,
        check=True,
        stdin=subprocess.DEVNULL,
        cwd="/",
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )


def provision_worker():
    try:
        pwd.getpwnam("knxohupdate")
    except KeyError:
        try:
            grp.getgrnam("knxohupdate")
        except KeyError:
            _run(["/usr/sbin/groupadd", "--system", "knxohupdate"])
        _run(
            [
                "/usr/sbin/useradd",
                "--system",
                "--gid",
                "knxohupdate",
                "--no-create-home",
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/usr/sbin/nologin",
                "knxohupdate",
            ]
        )
    worker = check_worker()
    check_worker_sudo()
    return worker


def _directory_at(path, gid, mode):
    # Never repair an unsafe existing path by following links/chowning its tree.
    _existing_chain(path.parent)
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o7022:
            raise ValueError("Unsafe provisioning destination")
    os.chown(path, 0, gid, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)


def provision_state(paths, worker):
    ui_gid = pwd.getpwnam("knxohui").pw_gid
    _directory_at(PREPARATION, worker.pw_gid, 0o750)
    _directory_at(paths.config_dir / ".updater-state", 0, 0o700)
    lease = paths.config_dir / ".updater-mutation.lock"
    with fs._parent(lease) as (_, parent, name, chain):
        try:
            fd = os.open(
                name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o660, dir_fd=parent
            )
        except FileExistsError:
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or info.st_nlink != 1
                or info.st_mode & 0o7007
            ):
                raise ValueError("Unsafe existing mutation lease")
            os.fchown(fd, 0, ui_gid)
            os.fchmod(fd, 0o660)
            os.fsync(fd)
            fs._check(chain)
            os.fsync(parent)
        finally:
            os.close(fd)
    # Status/log are created by StateStore as separate readable projections.
    # Never chown/chmod existing journal, replay ledger, gate or snapshots.
    projections = {
        ".updater-status.json": json.dumps(
            {"format_version": 1, "phase": "rolled-back", "message": "No update requested"},
            separators=(",", ":"),
        ).encode(),
        ".updater-log.txt": b"",
    }
    for name, raw in projections.items():
        path = paths.config_dir / name
        try:
            fs.read_regular(path, 16384)
        except FileNotFoundError:
            fs.atomic_write(path, raw, 0, 0, 0o644)


def _source_bytes(source, names):
    result = {}
    for name in names:
        path = source / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
            raise ValueError("Invalid verified bootstrap source")
        result[name] = path.read_bytes()
        if name.endswith((".sh", ".service", ".timer", ".sudoers")) and b"\r" in result[name]:
            raise ValueError("Bootstrap sources must have LF line endings")
    return result


def _exchange(left, right):
    # Linux renameat2 atomically exchanges complete directory trees. No interval
    # with a partially replaced import chain, no candidate self-update fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise OSError(errno.ENOSYS, "Atomic bundle exchange unavailable")
    if function(-100, os.fsencode(left), -100, os.fsencode(right), 2):
        raise OSError(ctypes.get_errno(), "Atomic bundle exchange failed")


def install_components(source, paths, paths_file):
    drops = render_dropins(paths, paths_file)
    sources = _source_bytes(
        source,
        (
            *BUNDLE,
            *HELPERS,
            *UNITS,
            "knxohui.sudoers",
            "service_update.sh",
            "knxohui-tmpfiles.conf",
        ),
    )
    # Validate ALL existing protected destinations before the first replacement.
    destinations = [POLICY, PACKAGE_HELPER, TMPFILES]
    destinations += [SYSTEMD / name for name in UNITS]
    destinations += [SYSTEMD / (name + ".d") / "50-knxohui-paths.conf" for name in drops]
    for path in destinations:
        _existing_chain(path.parent)
        try:
            fs.read_regular(path, 1024 * 1024)
        except FileNotFoundError:
            pass
    _existing_chain(LIBEXEC.parent)
    if LIBEXEC.exists() or LIBEXEC.is_symlink():
        _existing_chain(LIBEXEC)
        for directory, dirs, files in os.walk(LIBEXEC, followlinks=False):
            for name in dirs:
                _existing_chain(Path(directory) / name)
            for name in files:
                fs.read_regular(Path(directory) / name, 1024 * 1024)
    with tempfile.NamedTemporaryFile(dir="/run", prefix="knxohui-policy-") as policy:
        policy.write(sources["knxohui.sudoers"])
        policy.flush()
        _run(["/usr/sbin/visudo", "-cf", policy.name])
    # No changes until path, complete source, old bundle and policy validation.
    _directory_at(LIBEXEC.parent, 0, 0o755)
    staged = Path(tempfile.mkdtemp(prefix=".knxohui-bundle-", dir=LIBEXEC.parent))
    for name in (*BUNDLE, *HELPERS):
        path = staged / name
        path.parent.mkdir(exist_ok=True, mode=0o755)
        executable = name.endswith(".sh") or name == "set_ui_password.py"
        fs.atomic_write(path, sources[name], 0, 0, 0o755 if executable else 0o644)
    os.chmod(staged, 0o755)
    if LIBEXEC.exists():
        _exchange(staged, LIBEXEC)
        os.chmod(staged, 0o700)  # retained previous trusted bundle, no guessed deletion
    else:
        os.rename(staged, LIBEXEC)
    with fs._parent(LIBEXEC) as (_, parent, _, _):
        os.fsync(parent)
    for name in UNITS:
        fs.atomic_write(SYSTEMD / name, sources[name], 0, 0, 0o644)
    for name, text in drops.items():
        directory = SYSTEMD / (name + ".d")
        _directory_at(directory, 0, 0o755)
        fs.atomic_write(directory / "50-knxohui-paths.conf", text.encode(), 0, 0, 0o644)
    fs.atomic_write(POLICY, sources["knxohui.sudoers"], 0, 0, 0o440)
    fs.atomic_write(PACKAGE_HELPER, sources["service_update.sh"], 0, 0, 0o755)
    fs.atomic_write(TMPFILES, sources["knxohui-tmpfiles.conf"], 0, 0, 0o644)


@contextmanager
def installer_lease(paths, paths_file, inherited=None, lock=None):
    lock = LifecycleLock() if lock is None else lock
    context = lock.acquire() if inherited is None else lock.inherited(inherited)
    with context as fd:
        # A custom metadata argument must not hide a pending installation using
        # the canonical default: libexec/policy/host lock are shared by both.
        for contract in dict.fromkeys((PATHS_FILE, paths_file)):
            try:
                previous = load_paths(contract)
            except FileNotFoundError:
                continue
            check_clean_before_install(previous)
            if previous != paths:
                raise ValueError(
                    "Changing canonical paths requires separate administrator migration"
                )
        check_clean_before_install(paths)
        yield fd


def protected_fingerprint(paths, paths_file):
    """Bind rollback to exactly the pair/state this administrator prepared.

    A self-update or another administrator between phases may supersede it. Never
    restore an obsolete snapshot over those changes; retain evidence instead.
    """
    values = [str(_current_target(paths)[0])]
    for path in (
        paths_file,
        paths.config_dir / "config.json",
        paths.config_dir / "generator.json",
        paths.config_dir / "secrets.env",
        paths.config_dir / ".updater-state/journal.json",
    ):
        try:
            raw = fs.read_regular(path, 2 * 1024 * 1024)
            info = path.lstat()
            values.append(
                (
                    str(path),
                    hashlib.sha256(raw).hexdigest(),
                    info.st_uid,
                    info.st_gid,
                    stat.S_IMODE(info.st_mode),
                )
            )
        except FileNotFoundError:
            values.append((str(path), None))
    return values


def assert_unchanged(paths, paths_file, expected):
    if protected_fingerprint(paths, paths_file) != expected:
        raise ValueError("Installation superseded during activation; retain administrator evidence")


def read_outcome(path, paths):
    value = json.loads(fs.read_regular(path, 8192))
    flags = {
        "ui_start",
        "ui_enable",
        "cleanup_start",
        "cleanup_enable",
        "ui_was_active",
        "ui_was_enabled",
        "cleanup_service_was_active",
        "cleanup_timer_was_active",
        "cleanup_timer_was_enabled",
    }
    if (
        not isinstance(value, dict)
        or set(value) != flags | {"mode", "release", "previous", "snapshot_file"}
        or value["mode"] not in ("install", "repair", "failed")
        or any(type(value[key]) is not bool for key in flags)
    ):
        raise ValueError("Invalid administrator setup outcome")
    for key in ("release", "previous"):
        if value[key] and fs._canonical(Path(value[key])).parent != paths.releases:
            raise ValueError("Administrator release outside managed layout")
    if value["snapshot_file"] and Path(value["snapshot_file"]) != (
        Path(value["release"]) / ".migration-snapshot-path"
    ):
        raise ValueError("Invalid administrator snapshot marker")
    return value


def rollback_setup(source, paths, outcome):
    # Caller has REACQUIRED the host lease and checked the exact fingerprint.
    # The recovery unit is already complete; no service starts while we hold it.
    write_gate(paths, "deny", None, None)
    for name in (
        "knxohui-backup-cleanup.timer",
        "knxohui-backup-cleanup.service",
        "knxohui.service",
    ):
        _run(["/usr/bin/systemctl", "stop", name])
    if outcome["mode"] == "install":
        marker = Path(outcome["snapshot_file"])
        snapshot = Path(fs.read_regular(marker, 4096).decode().strip())
        fs._canonical(snapshot)
        expected = paths.config_dir / ".installer-state"
        if expected not in snapshot.parents:
            raise ValueError("Snapshot outside protected administrator state")
        _run(
            [
                "/usr/bin/python3",
                "-I",
                str(source / "config_migrations.py"),
                "--restore-snapshot",
                str(snapshot),
            ]
        )
    if outcome["previous"]:
        target = fs._canonical(Path(outcome["previous"]))
        _directory(target)
        with fs._parent(paths.current) as (_, parent, name, chain):
            temporary = ".bootstrap-rollback-" + str(uuid4())
            os.symlink(str(target), temporary, dir_fd=parent)
            fs._check(chain)
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
    else:
        with fs._parent(paths.current) as (_, parent, name, chain):
            fs._check(chain)
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
    if outcome["release"] and Path(outcome["release"]).exists():
        fs.atomic_write(Path(outcome["release"]) / ".install-incomplete", b"", 0, 0, 0o600)
    write_gate(paths, "clear", None, None)


def execute_setup(source, paths, paths_file, options, inherited=None):
    with tempfile.TemporaryDirectory(prefix="knxohui-bootstrap-", dir="/run") as scratch:
        result_file = Path(scratch) / "outcome.json"
        with installer_lease(paths, paths_file, inherited) as fd:
            # A terminal updater journal binds its current target. Administrator
            # repair may upgrade the trusted bundle, but must not silently reset
            # its replay ledger by installing a different application version.
            journal = paths.config_dir / ".updater-state/journal.json"
            if journal.exists() and "--repair" not in options:
                raise ValueError(
                    "Retained updater journal: use verified --repair for trusted code, "
                    "then the release updater; do not discard its replay ledger"
                )
            if journal.exists() and "--activate-existing" in options:
                raise ValueError(
                    "Retained updater journal forbids administrator target replacement; "
                    "repair the trusted bundle without --activate-existing"
                )
            environment = {
                key: value for key, value in os.environ.items() if key.startswith("KNXOH_")
            }
            environment.update(
                KNXOH_LIFECYCLE_FD=str(fd),
                KNXOH_SETUP_ROOT=str(source.parent),
                KNXOH_BOOTSTRAP_OUTCOME=str(result_file),
                KNXOH_INSTALL_DIR=str(paths.releases.parent),
                KNXOH_CONFIG_DIR=str(paths.config_dir),
                KNXOH_DATA_DIR=str(paths.data_dir),
                KNXOH_BACKUP_DIR=str(paths.backup_dir),
                KNXOH_PATHS_FILE=str(paths_file),
                PATH="/usr/sbin:/usr/bin:/sbin:/bin",
                LANG="C.UTF-8",
                HOME="/root",
            )
            result = subprocess.run(
                ["/bin/bash", str(source / "setup.sh"), *options],
                env=environment,
                cwd="/",
                pass_fds=(fd,),
                check=False,
            )
            if result.returncode and not result_file.exists():
                return result.returncode  # failed disk rollback: no writers may be restored
            outcome = read_outcome(result_file, paths)
            expected = None if result.returncode else protected_fingerprint(paths, paths_file)
        if result.returncode:
            # Child already restored disk state while holding the lease. Its
            # root-authored result only schedules fixed service operations.
            restore_services(outcome, _run)
            return result.returncode
        # No disk mutations here: the required recovery unit takes its own lease.
        try:
            activate_services(outcome, _run)
        except (OSError, subprocess.SubprocessError):
            with installer_lease(paths, paths_file) as _:
                assert_unchanged(paths, paths_file, expected)
                rollback_setup(source, paths, outcome)
            if outcome["previous"]:
                restore_services(outcome, _run)
            raise ValueError(
                "Administrator activation failed; prior pair restored, evidence retained"
            )
        if outcome["mode"] == "install":
            try:
                with installer_lease(paths, paths_file):
                    assert_unchanged(paths, paths_file, expected)
                    # Existing verified administrator migration cleanup, NOT
                    # current/candidate code. This venv was created by THIS
                    # administrator operation; the unchanged-pair check and host
                    # lease prevent substituting a worker-produced environment.
                    _run(
                        [
                            str(Path(outcome["release"]) / "venv/bin/python"),
                            "-I",
                            str(source / "migrate_runtime_data.py"),
                            "--source-root",
                            str(paths.releases.parent),
                            "--template-root",
                            outcome["release"],
                            "--config-dir",
                            str(paths.config_dir),
                            "--data-dir",
                            str(paths.data_dir),
                            "--backup-dir",
                            str(paths.backup_dir),
                            "--install-dir",
                            str(paths.releases.parent),
                            "--paths-file",
                            str(paths_file),
                            "--cleanup-legacy",
                            "--snapshot-backup-dir",
                            str(paths.config_dir / ".installer-state"),
                        ]
                    )
                    for name in (".migration-snapshot-path", ".installer-transaction-state"):
                        _unlink(Path(outcome["release"]) / name)
            except (OSError, ValueError, subprocess.SubprocessError):
                # As before: successful activation is not rolled back because
                # optional legacy cleanup failed or another operation superseded
                # it. Never discard sibling data or stale evidence as a fallback.
                print("Legacy cleanup deferred; administrator evidence retained", file=sys.stderr)
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("setup", "validate", "provision"), required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--paths-file", type=Path, default=PATHS_FILE)
    parser.add_argument("options", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if os.name != "posix" or not sys.flags.isolated or os.geteuid() != 0:
        raise ValueError("Administrator bootstrap requires isolated system Python as root")
    paths = Paths(
        args.base / "releases",
        args.base / "current",
        args.config_dir,
        args.data_dir,
        args.backup_dir,
    )
    render_dropins(paths, args.paths_file)
    inherited = os.environ.get("KNXOH_LIFECYCLE_FD")
    inherited = None if inherited is None else int(inherited)
    source = Path(__file__).parent
    options = args.options[1:] if args.options[:1] == ["--"] else args.options
    if args.action == "setup":
        return execute_setup(source, paths, args.paths_file, options, inherited)
    with installer_lease(paths, args.paths_file, inherited):
        if args.action == "validate":
            if inherited is None:
                raise ValueError("Missing inherited lifecycle descriptor")
            return 0
        if args.action == "provision":
            if inherited is None:
                raise ValueError("Provisioning requires the live setup lease")
            worker = provision_worker()
            provision_state(paths, worker)
            install_components(source, paths, args.paths_file)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Bootstrap refused: {error}", file=sys.stderr)
        raise SystemExit(2)
