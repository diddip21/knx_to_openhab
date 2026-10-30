"""Real Linux collector round trip in a private, path-mapped filesystem.

No manager or application command is run. chroot maps the fixed fixture paths to
test-owned files; an anchored real proc descriptor keeps secure_fs's actual kernel
fdinfo checks available without mounting anything or fabricating metadata.
"""

import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="real collector integration requires Linux root and a private chroot fixture",
)


def test_real_collector_serialization_and_full_installed_validation(monkeypatch):
    import grp
    import pwd

    from installer import update_bootstrap as admin
    from installer.update_core import secure_fs as fs
    from scripts import nested_fixture_repair as repair
    from scripts import nested_fixture_state as state
    from scripts import nested_systemd_fixture as fixture

    nonce = "ab" * 32
    source = Path(admin.__file__).resolve().parents[1]
    names = {
        *(
            "installer/" + name
            for name in (
                *admin.BUNDLE,
                *admin.HELPERS,
                *admin.UNITS,
                "update_bootstrap.py",
                "bootstrap_activation.py",
                "knxohui.sudoers",
                "service_update.sh",
                "knxohui-tmpfiles.conf",
            )
        ),
        "requirements.txt",
        "VERSION",
        "config.json",
    }
    payloads = {name: (source / name).read_bytes() for name in names}
    expected = repair._component_files(admin, source)
    initial = Path(str(repair.INITIAL))
    old_root = Path("/opt/knxoh-source-" + repair.OLD_HEAD)
    old_files = {
        name: dict(
            sha256=hashlib.sha256(raw).hexdigest(), mode=0o755 if name.endswith(".sh") else 0o644
        )
        for name, raw in payloads.items()
    }
    old = dict(
        format=1,
        purpose="reviewed-sudo-fix-source",
        head=repair.OLD_HEAD,
        production_base="27d106a26c907b7ce05d1880ea25157b1f815e50",
        review_approved=True,
        root=str(old_root),
        archive_sha256=repair.OLD_ARCHIVE_SHA256,
        files=old_files,
    )
    # Synthetic source approval, fixed from the seed bytes, never from collection.
    monkeypatch.setattr(
        repair,
        "OLD_FILES_SHA256",
        hashlib.sha256(
            json.dumps(old_files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    identities = {
        "knxohui": SimpleNamespace(
            pw_uid=999, pw_gid=989, pw_shell="/usr/sbin/nologin", pw_dir="/nonexistent"
        ),
        "knxohupdate": SimpleNamespace(
            pw_uid=997, pw_gid=988, pw_shell="/usr/sbin/nologin", pw_dir="/nonexistent"
        ),
    }
    groups = {
        name: SimpleNamespace(gr_gid=account.pw_gid, gr_mem=[], gr_name=name)
        for name, account in identities.items()
    }
    monkeypatch.setattr(pwd, "getpwnam", identities.__getitem__)
    monkeypatch.setattr(grp, "getgrnam", groups.__getitem__)
    monkeypatch.setattr(grp, "getgrall", lambda: list(groups.values()))
    monkeypatch.setattr(os, "getgrouplist", lambda name, gid: [gid])
    monkeypatch.setattr(socket, "gethostname", lambda: "localhost")
    units = {
        unit: dict(
            LoadState="loaded",
            ActiveState="inactive",
            SubState="dead",
            MainPID="0",
            Result="success",
            ExecMainStatus="0",
            NRestarts="0",
            UnitFileState="enabled",
        )
        for unit in state.UNITS
    }
    units[state.UNITS[4]].update(ActiveState="active", SubState="exited")
    monkeypatch.setattr(repair, "manager_state", lambda: dict(units=units, jobs=[]))
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    proc_fd = os.open("/proc/self/fdinfo", os.O_RDONLY | os.O_DIRECTORY)

    def kernel_open(name, *, encoding):
        assert name.startswith("/proc/self/fdinfo/")
        return os.fdopen(
            os.open(name.rsplit("/", 1)[1], os.O_RDONLY, dir_fd=proc_fd), encoding=encoding
        )

    monkeypatch.setattr(fs, "open", kernel_open, raising=False)
    # All temporary writes stay under /root, never the actual fixed app paths.
    with tempfile.TemporaryDirectory(prefix="knxoh-collector-test-", dir="/root") as temporary:
        root = Path(temporary)
        root.chmod(0o755)

        def seed(path, raw=None, mode=0o755, uid=0, gid=0):
            target = root / str(path).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            if raw is None:
                target.mkdir(exist_ok=True)
            else:
                target.write_bytes(raw)
            target.chmod(mode)
            os.chown(target, uid, gid)

        for path, (uid, gid, mode, _) in repair._noncomponent_directories().items():
            seed(path, uid=uid, gid=gid, mode=mode)
        for name in ("jobs", "staging", "generated"):
            seed(state.DATA / name, mode=0o750, uid=999, gid=989)
        seed(state.CONFIG / ".updater-state", mode=0o700)
        frozen = {
            state.CONFIG / "config.json": (b'{"fixture":"config"}', 989, 0o640),
            state.CONFIG / "generator.json": (payloads["config.json"], 989, 0o640),
            state.PATHS_FILE: (b"fixture paths", 0, 0o644),
            Path("/etc/hosts"): (b"127.0.0.1 localhost\n", 0, 0o644),
            state.RECEIPT: (b"private synthetic receipt", 0, 0o600),
            state.LOCK: (b"", 0, 0o600),
        }
        specs = state.recorded_specs(nonce)
        for path, (raw, gid, mode) in frozen.items():
            seed(path, raw, mode, gid=gid)
            specs[str(path)]["sha256"] = hashlib.sha256(raw).hexdigest()
        monkeypatch.setattr(state, "recorded_specs", lambda nonce: specs)
        for name, gid, mode in (
            ("secrets.env", 989, 0o640),
            (".updater-mutation.lock", 989, 0o660),
            (".updater-status.json", 0, 0o644),
            (".updater-log.txt", 0, 0o644),
        ):
            seed(state.CONFIG / name, b"synthetic", mode, gid=gid)
        seed("/root/knxoh-acceptance-login.json", b"synthetic login", 0o600)
        for folder, name in {
            "items": "knx.items",
            "things": "knx.things",
            "sitemaps": "knx.sitemap",
            "persistence": "influxdb.persist",
            "rules": "fenster.rules",
        }.items():
            seed(state.OUTPUT / folder)
            seed(state.OUTPUT / folder / name, b"", 0o644, 999, 989)
        for name, raw in payloads.items():
            seed(old_root / name, raw, old_files[name]["mode"])
            seed(initial / name, raw, old_files[name]["mode"])
        seed(initial / "venv")
        count = len(list((root / str(initial).lstrip("/")).rglob("*"))) + 1
        for index in range(3354 - count):
            seed(initial / "venv" / f"dependency{index}", b"inert", 0o644)
        current = root / str(state.BASE / "current").lstrip("/")
        current.symlink_to(initial)
        for name, (raw, mode) in expected.items():
            seed(name, raw, mode)
        for name, target in repair._systemd_enable_links().items():
            if name.startswith("/etc/"):
                destination = root / name.lstrip("/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(target)
        # Genuine shared parents contain non-app OS policy siblings. Their bytes
        # must not enter collection or be required to match the component set.
        seed("/etc/sudoers.d/README", b"UNRELATED PRIVATE POLICY CONTENT", 0o440)
        seed("/etc/tmpfiles.d/system.conf", b"UNRELATED PRIVATE POLICY CONTENT", 0o600)
        seed("/etc/sudoers.d", mode=0o750)
        seed("/etc/machine-id", repair.MACHINE_ID.encode(), 0o644)
        seed("/proc/sys/kernel/random/boot_id", repair.BOOT_ID.encode(), 0o644)
        os.chroot(root)
        os.chdir("/")
        try:
            state.verify_source_approval(old, repair.OLD_HEAD)

            def pipeline():
                # The exact real collector output is serialized, not augmented,
                # filtered, path-rewritten, or repaired before either validator.
                inventory = json.loads(json.dumps(repair.collect_installed()))
                checkpoint = dict(
                    format=1,
                    checkpoint="environmentfile-installed-20261030",
                    nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest(),
                    old_source_approval=old,
                    inventory=inventory,
                )
                repair.validate_repair_checkpoint(checkpoint, inventory, nonce)
                repair.validate_installed_components(fixture, checkpoint, inventory)
                return checkpoint

            checkpoint = pipeline()
            entries = checkpoint["inventory"]["entries"]
            assert (
                len(
                    [name for name in entries if name == str(initial) or str(initial) + "/" in name]
                )
                == 3354
            )
            for name in ("/etc/sudoers.d", "/etc/tmpfiles.d"):
                info = Path(name).lstat()
                assert (entries[name]["device"], entries[name]["inode"]) == (
                    info.st_dev,
                    info.st_ino,
                )
            assert "/etc/sudoers.d/README" not in entries
            assert "/etc/tmpfiles.d/system.conf" not in entries
            assert "UNRELATED PRIVATE POLICY CONTENT" not in json.dumps(checkpoint)
            for parent in (Path("/etc/sudoers.d"), Path("/etc/tmpfiles.d")):
                original_mode = 0o750 if parent.name == "sudoers.d" else 0o755
                for uid, gid, mode in (
                    (999, 0, original_mode),
                    (0, 999, original_mode),
                    (0, 0, 0o777),
                    (0, 0, 0o755 if original_mode == 0o750 else 0o750),
                ):
                    os.chown(parent, uid, gid)
                    parent.chmod(mode)
                    try:
                        with pytest.raises(ValueError):
                            pipeline()
                    finally:
                        os.chown(parent, 0, 0)
                        parent.chmod(original_mode)
                extra = parent / "knxoh-review-extra"
                extra.write_bytes(b"not approved")
                try:
                    with pytest.raises(ValueError):
                        pipeline()
                finally:
                    extra.unlink()
                saved = parent.with_name(parent.name + "-saved")
                parent.rename(saved)
                parent.symlink_to(saved, target_is_directory=True)
                try:
                    with pytest.raises(ValueError):
                        pipeline()
                finally:
                    parent.unlink()
                    saved.rename(parent)
                # Same bytes/modes/names on a replacement parent are not the
                # original inode. Validation must not silently update the pin.
                parent.rename(saved)
                shutil.copytree(saved, parent)
                try:
                    replacement = pipeline()
                    assert (
                        replacement["inventory"]["entries"][str(parent)]["inode"]
                        != entries[str(parent)]["inode"]
                    )
                    with pytest.raises(ValueError, match="mismatch"):
                        repair.validate_repair_checkpoint(
                            checkpoint, replacement["inventory"], nonce
                        )
                finally:
                    shutil.rmtree(parent)
                    saved.rename(parent)
            assert pipeline() == checkpoint
            # Ignoring our own read atime must not hide an actual link swap.
            original_readlink = os.readlink
            swapped = []

            def swapping_readlink(path, *args, **kwargs):
                target = original_readlink(path, *args, **kwargs)
                if path == state.BASE / "current" and not swapped:
                    swapped.append(True)
                    path.unlink()
                    path.symlink_to(initial / "wrong")
                return target

            try:
                with monkeypatch.context() as race:
                    race.setattr(os, "readlink", swapping_readlink)
                    with pytest.raises(ValueError, match="link changed"):
                        repair.collect_installed()
                assert swapped
            finally:
                Path(state.BASE / "current").unlink()
                Path(state.BASE / "current").symlink_to(initial)
        finally:
            os.fchdir(root_fd)
            os.chroot(".")
            os.chdir("/")
            os.close(root_fd)
            os.close(proc_fd)
