"""Portable repair boundaries; no guest, WSL or service manager calls."""

import copy
import hashlib
import importlib
import json
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from scripts import nested_fixture_state as state
from scripts import nested_systemd_fixture as fixture
from scripts import run_nested_systemd_acceptance as runner

NONCE = "ab" * 32
HEAD = "de" * 20


def repair_module():
    return importlib.import_module("scripts.nested_fixture_repair")


def test_repair_phase_requires_all_pins_before_guest_program():
    with pytest.raises(ValueError, match="pinned checkpoint"):
        runner.guest_program("repair-environmentfile", NONCE)


@pytest.fixture
def boundary(monkeypatch):
    repair = repair_module()
    events = []
    inventory = {"entries": {str(state.LOCK): {"inode": 1}}, "frozen": "initial"}
    checkpoint = {"inventory": copy.deepcopy(inventory)}
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: events.append("guest"))
    monkeypatch.setattr(repair, "collect_installed", lambda: copy.deepcopy(inventory))
    monkeypatch.setattr(
        repair,
        "validate_repair_checkpoint",
        lambda pin, actual, nonce: (
            None
            if pin["inventory"] == actual
            else (_ for _ in ()).throw(ValueError("checkpoint mismatch"))
        ),
    )
    monkeypatch.setattr(
        repair, "verify_repair_sources", lambda *a: events.append("sources") or fixture.SOURCE
    )
    monkeypatch.setattr(
        repair, "validate_installed_components", lambda *a: events.append("components")
    )
    monkeypatch.setattr(repair, "verify_preserved", lambda *a: events.append("preserved"))
    monkeypatch.setattr(repair, "verify_repaired", lambda *a: events.append("new-components"))
    admin = SimpleNamespace(
        check_worker=lambda: events.append("worker"),
        check_worker_sudo=lambda: events.append("sudo"),
        install_components=lambda *a: events.append("install"),
        Paths=type(fixture.expected_paths()),
    )
    monkeypatch.setattr(fixture, "load_approved_admin", lambda *a: admin)

    @contextmanager
    def lease(*a):
        events.append("lock")
        yield
        events.append("unlock")

    monkeypatch.setattr(fixture, "resume_lease", lease)
    monkeypatch.setattr(repair, "activate_repaired", lambda *a: events.append("activate"))
    return repair, inventory, checkpoint, events, admin


def test_repair_only_installs_components_under_lease_then_activates(boundary):
    repair, _, checkpoint, events, _ = boundary
    repair.repair_environmentfile(fixture, NONCE, checkpoint, {}, HEAD)
    assert events == [
        "guest",
        "sources",
        "components",
        "lock",
        "guest",
        "sources",
        "components",
        "worker",
        "sudo",
        "install",
        "preserved",
        "new-components",
        "unlock",
        "activate",
    ]


@pytest.mark.parametrize("under_lock", [False, True])
def test_changed_snapshot_has_zero_install_or_activation_effects(boundary, monkeypatch, under_lock):
    repair, inventory, checkpoint, events, _ = boundary
    calls = []

    def collect():
        calls.append(1)
        result = copy.deepcopy(inventory)
        if len(calls) > int(under_lock):
            result["frozen"] = "unexpected"
        return result

    monkeypatch.setattr(repair, "collect_installed", collect)
    with pytest.raises(ValueError, match="checkpoint mismatch"):
        repair.repair_environmentfile(fixture, NONCE, checkpoint, {}, HEAD)
    assert "install" not in events and "activate" not in events


def test_policy_failure_does_not_install(boundary):
    repair, _, checkpoint, events, admin = boundary
    admin.check_worker_sudo = lambda: (_ for _ in ()).throw(ValueError("sudo refused"))
    with pytest.raises(ValueError, match="sudo refused"):
        repair.repair_environmentfile(fixture, NONCE, checkpoint, {}, HEAD)
    assert "install" not in events and "activate" not in events


@pytest.mark.parametrize("field", ["inode", "sha256", "mode", "uid", "gid", "children"])
def test_frozen_inventory_comparison_rejects_stale_metadata(field):
    repair = repair_module()
    before = {"entries": {str(state.CONFIG / "secrets.env"): {field: "old"}}}
    after = copy.deepcopy(before)
    after["entries"][str(state.CONFIG / "secrets.env")][field] = "changed"
    with pytest.raises(ValueError, match="preserved"):
        repair.verify_preserved(before, after)


def test_repair_source_requires_new_commit_and_unchanged_dependency_contract():
    repair = repair_module()
    with pytest.raises(ValueError):
        repair.validate_repair_source({}, repair.OLD_HEAD, {})


def test_activation_failure_stops_own_writers_and_reports_state(monkeypatch):
    repair = repair_module()
    events = []

    def command(argv, **kwargs):
        events.append(argv)
        if "daemon-reload" in argv:
            raise RuntimeError("real activation failed")

    fake = SimpleNamespace(
        require_guest=lambda nonce: None,
        command=command,
    )
    admin = SimpleNamespace(
        activate_services=lambda outcome, run: run(["/usr/bin/systemctl", "daemon-reload"])
    )
    monkeypatch.setattr(repair, "manager_state", lambda: events.append("state") or {})
    with pytest.raises(RuntimeError, match="real activation failed"):
        repair.activate_repaired(fake, NONCE, admin)
    assert events[1] == [
        "/usr/bin/systemctl",
        "stop",
        "--",
        "knxohui.service",
        "knxohui-backup-cleanup.timer",
        "knxohui-backup-cleanup.service",
    ]
    assert events[-1] == "state"


@pytest.mark.parametrize("failure", ["sources", "components", "preserved", "new-components"])
def test_boundary_failure_never_activates(boundary, monkeypatch, failure):
    repair, _, checkpoint, events, _ = boundary
    name = {
        "sources": "verify_repair_sources",
        "components": "validate_installed_components",
        "preserved": "verify_preserved",
        "new-components": "verify_repaired",
    }[failure]
    monkeypatch.setattr(repair, name, lambda *a: (_ for _ in ()).throw(ValueError(failure)))
    with pytest.raises(ValueError, match=failure):
        repair.repair_environmentfile(fixture, NONCE, checkpoint, {}, HEAD)
    assert "activate" not in events
    if failure in ("sources", "components"):
        assert "install" not in events


def test_preserved_allows_only_declared_component_replacements():
    repair = repair_module()
    config = str(state.CONFIG / "config.json")
    unit = "/etc/systemd/system/knxohui.service"
    old = {"entries": {config: {"inode": 1}, unit: {"inode": 2}}, "accounts": {}}
    new = copy.deepcopy(old)
    new["entries"][unit]["inode"] = 3
    repair.verify_preserved(old, new)
    new["entries"][config]["inode"] = 4
    with pytest.raises(ValueError, match="preserved"):
        repair.verify_preserved(old, new)


@pytest.mark.parametrize("change", ["extra", "delete", "requirements", "runtime", "mode"])
def test_source_delta_is_frozen_except_rendering_and_regressions(change):
    repair = repair_module()
    old = {
        "installer/update_bootstrap.py": {"sha256": "a" * 64, "mode": 0o644},
        "requirements.txt": {"sha256": "b" * 64, "mode": 0o644},
        "installer/update_core/state.py": {"sha256": "c" * 64, "mode": 0o644},
    }
    new = copy.deepcopy(old)
    new["installer/update_bootstrap.py"]["sha256"] = "d" * 64
    if change == "extra":
        new["new.py"] = old["requirements.txt"]
    elif change == "delete":
        del new["requirements.txt"]
    elif change == "requirements":
        new["requirements.txt"]["sha256"] = "e" * 64
    elif change == "runtime":
        new["installer/update_core/state.py"]["sha256"] = "e" * 64
    else:
        new["installer/update_bootstrap.py"]["mode"] = 0o755
    with pytest.raises(ValueError, match="source delta"):
        repair.validate_source_delta(old, new)


def test_source_delta_requires_changed_renderer():
    repair = repair_module()
    files = {"installer/update_bootstrap.py": {"sha256": "a" * 64, "mode": 0o644}}
    with pytest.raises(ValueError, match="source delta"):
        repair.validate_source_delta(files, files)
    new = copy.deepcopy(files)
    new["installer/update_bootstrap.py"]["sha256"] = "b" * 64
    repair.validate_source_delta(files, new)


@pytest.mark.parametrize("bad", [{}, {"format": 1}, {"checkpoint": "after-sudo-denial-20261030"}])
def test_unapproved_or_old_checkpoint_schema_refuses(bad):
    with pytest.raises(ValueError, match="checkpoint"):
        repair_module().validate_repair_checkpoint(bad, {}, NONCE)


def test_manager_precondition_rejects_writers_jobs_and_bad_recovery():
    repair = repair_module()
    states = {}
    for unit in state.UNITS:
        states[unit] = dict(
            LoadState="loaded",
            ActiveState="inactive",
            SubState="dead",
            MainPID="0",
            Result="success",
            ExecMainStatus="0",
            NRestarts="0",
            UnitFileState="enabled",
        )
    recovery = states[state.UNITS[4]]
    recovery.update(ActiveState="active", SubState="exited")
    value = {"units": states, "jobs": []}
    repair.validate_manager(value)
    for unit, key, bad in [
        (state.UNITS[0], "MainPID", "123"),
        (state.UNITS[1], "ActiveState", "active"),
        (state.UNITS[4], "Result", "exit-code"),
    ]:
        changed = copy.deepcopy(value)
        changed["units"][unit][key] = bad
        with pytest.raises(ValueError, match="manager"):
            repair.validate_manager(changed)
    value["jobs"] = [[123, state.UNITS[0], "start", "waiting"]]
    with pytest.raises(ValueError, match="manager"):
        repair.validate_manager(value)


@pytest.fixture
def installed_inventory():
    repair = repair_module()
    entries = copy.deepcopy(state.recorded_specs(NONCE))

    def directory(path, uid=0, gid=0, mode=0o755, children=()):
        entries[path.as_posix()] = dict(
            kind="directory", uid=uid, gid=gid, mode=mode, children=sorted(children)
        )

    def file(path, gid=0, mode=0o644):
        entries[
            PurePosixPath(path.as_posix() if hasattr(path, "as_posix") else path).as_posix()
        ] = dict(kind="file", uid=0, gid=gid, mode=mode, sha256="a" * 64, links=1)

    directory(state.BASE, children=["current", "releases"])
    directory(state.BASE / "releases", children=["0.1.0"])
    directory(repair.INITIAL, children=["venv", *(f"file{i}" for i in range(3352))])
    directory(repair.INITIAL / "venv")
    for i in range(3352):
        file(repair.INITIAL / f"file{i}")
    directory(state.PREPARATION, gid=988, mode=0o750)
    directory(state.CONFIG / ".updater-state", mode=0o700)
    file(state.CONFIG / "secrets.env", gid=989, mode=0o640)
    file(state.CONFIG / ".updater-mutation.lock", gid=989, mode=0o660)
    file(state.CONFIG / ".updater-status.json")
    file(state.CONFIG / ".updater-log.txt")
    file("/root/knxoh-acceptance-login.json", mode=0o600)
    output_files = {
        "items": "knx.items",
        "things": "knx.things",
        "sitemaps": "knx.sitemap",
        "persistence": "influxdb.persist",
        "rules": "fenster.rules",
    }
    directory(state.OUTPUT, children=output_files)
    for folder, name in output_files.items():
        directory(state.OUTPUT / folder, children=[name])
        file(state.OUTPUT / folder / name, gid=989)
        entries[(state.OUTPUT / folder / name).as_posix()].update(
            uid=999, sha256=hashlib.sha256(b"").hexdigest()
        )
    directory(
        state.CONFIG,
        gid=989,
        mode=0o750,
        children=[
            "config.json",
            "generator.json",
            "paths.env",
            "secrets.env",
            ".updater-state",
            ".updater-mutation.lock",
            ".updater-status.json",
            ".updater-log.txt",
        ],
    )
    entries[(state.BASE / "current").as_posix()] = dict(
        kind="other", uid=0, gid=0, mode=0o777, links=1, target=str(repair.INITIAL)
    )
    for i, value in enumerate(entries.values(), 1):
        value.update(device=1, inode=i)
        value.setdefault("links", 2)
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
    return dict(
        entries=entries,
        hostname="localhost",
        machine_id=repair.MACHINE_ID,
        boot_id=repair.BOOT_ID,
        manager=dict(units=units, jobs=[]),
        accounts={
            "knxohui": dict(
                uid=999, gid=989, groups=[989], shell="/usr/sbin/nologin", home="/nonexistent"
            ),
            "knxohupdate": dict(
                uid=997, gid=988, groups=[988], shell="/usr/sbin/nologin", home="/nonexistent"
            ),
        },
        groups={"knxohui": dict(gid=989, members=[]), "knxohupdate": dict(gid=988, members=[])},
        aliases={"knxohui": ["knxohui"], "knxohupdate": ["knxohupdate"]},
    )


def test_full_synthetic_installed_inventory_is_not_fresh_or_after_sudo(installed_inventory):
    repair = repair_module()
    repair.validate_known_inventory(installed_inventory, NONCE)
    with pytest.raises(ValueError):
        state.validate_fresh(installed_inventory)
    with pytest.raises(ValueError):
        state.validate_recorded_partial(installed_inventory, NONCE)


@pytest.mark.parametrize(
    "change",
    [
        "boot",
        "machine",
        "receipt",
        "current",
        "config",
        "group",
        "alias",
        "hostname",
        "venv-owner",
        "venv-link",
        "venv-missing",
        "initial-extra",
        "secret-mode",
        "mutation-mode",
        "jobs",
        "journal",
        "maintenance",
        "gate",
        "default",
        "bundle",
        "bool-inode",
        "bad-digest",
        "extra-field",
    ],
)
def test_even_reapproved_unknown_checkpoint_is_not_adopted(installed_inventory, change):
    repair = repair_module()
    value = installed_inventory
    entries = value["entries"]
    if change in ("boot", "machine", "hostname"):
        value[{"boot": "boot_id", "machine": "machine_id", "hostname": "hostname"}[change]] = (
            "unknown"
        )
    elif change == "receipt":
        entries[state.RECEIPT.as_posix()]["sha256"] = "0" * 64
    elif change == "current":
        entries[(state.BASE / "current").as_posix()]["target"] = "/unknown"
    elif change == "config":
        entries[(state.CONFIG / "config.json").as_posix()]["sha256"] = "0" * 64
    elif change == "group":
        value["accounts"]["knxohupdate"]["groups"].append(27)
    elif change == "alias":
        value["aliases"]["knxohupdate"].append("sudo")
    elif change in ("venv-owner", "venv-link"):
        entries[str(repair.INITIAL / "venv")]["uid" if change == "venv-owner" else "kind"] = (
            997 if change == "venv-owner" else "other"
        )
    elif change == "venv-missing":
        del entries[str(repair.INITIAL / "venv")]
    elif change in ("secret-mode", "mutation-mode"):
        entries[
            (
                state.CONFIG
                / ("secrets.env" if change == "secret-mode" else ".updater-mutation.lock")
            ).as_posix()
        ]["mode"] = 0o666
    elif change in ("jobs", "journal", "maintenance", "gate"):
        path, child = {
            "jobs": (state.DATA / "jobs", "request.json"),
            "journal": (state.CONFIG / ".updater-state", "journal.json"),
            "maintenance": (state.CONFIG, ".updater-maintenance.json"),
            "gate": (state.CONFIG, ".updater-startup-gate.json"),
        }[change]
        entries[path.as_posix()]["children"].append(child)
        entries[path.as_posix()]["children"].sort()
    elif change in ("initial-extra", "default", "bundle"):
        name = {
            "initial-extra": str(repair.INITIAL / "extra"),
            "default": "/etc/knx_to_openhab",
            "bundle": "/usr/local/libexec/.knxohui-bundle-unknown",
        }[change]
        entries[name] = copy.deepcopy(entries[str(repair.INITIAL / "venv")])
    else:
        entry = entries[str(repair.INITIAL / "file0")]
        entry[
            {"bool-inode": "inode", "bad-digest": "sha256", "extra-field": "raw_secret"}[change]
        ] = True
    with pytest.raises(ValueError):
        repair.validate_known_inventory(value, NONCE)


def test_locked_manager_state_must_also_be_preserved():
    repair = repair_module()
    before = {"entries": {}, "manager": {"writer": "stopped"}}
    after = {"entries": {}, "manager": {"writer": "started"}}
    with pytest.raises(ValueError, match="preserved"):
        repair.verify_preserved(before, after)


def test_checkpoint_cannot_adopt_unknown_generated_output(installed_inventory):
    repair = repair_module()
    installed_inventory["entries"][state.OUTPUT.as_posix()]["children"].append("unknown")
    installed_inventory["entries"][state.OUTPUT.as_posix()]["children"].sort()
    with pytest.raises(ValueError, match="checkpoint"):
        repair.validate_known_inventory(installed_inventory, NONCE)


def test_checkpoint_binds_exact_full_inventory_without_nonce_plaintext(
    monkeypatch, installed_inventory
):
    repair = repair_module()
    monkeypatch.setattr(repair, "validate_old_source", lambda value: None)
    pin = dict(
        format=1,
        checkpoint="environmentfile-installed-20261030",
        nonce_sha256=hashlib.sha256(NONCE.encode()).hexdigest(),
        old_source_approval={},
        inventory=copy.deepcopy(installed_inventory),
    )
    repair.validate_repair_checkpoint(pin, installed_inventory, NONCE)
    assert NONCE not in json.dumps(pin)
    installed_inventory["entries"][str(repair.INITIAL / "file0")]["inode"] += 1
    with pytest.raises(ValueError, match="mismatch"):
        repair.validate_repair_checkpoint(pin, installed_inventory, NONCE)


@pytest.fixture
def portable_tree(monkeypatch, tmp_path):
    """Real offline files behind a descriptor fake, not a POSIX security proof."""
    import os
    import stat
    from contextlib import ExitStack

    repair = repair_module()
    root = tmp_path / "initial"
    (root / "venv/bin").mkdir(parents=True)
    sentinel = tmp_path / "must-not-execute"
    (root / "venv/bin/python").write_text(f"raise RuntimeError({str(sentinel)!r})")
    (root / "credentials.env").write_bytes(b"not-a-real-credential")
    opened = {}
    checked = []

    @contextmanager
    def parent(path):
        with ExitStack() as stack:
            yield stack, None, root.name, []

    def open_entry(stack, parent, name, owners, device, directory=False):
        path = (root.parent if parent is None else opened[parent][0]) / name
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
        ):
            raise ValueError("unsafe offline entry")
        if not directory and info.st_nlink != 1:
            raise ValueError("unsafe offline links")
        fd = len(opened) + 1
        stream = None if directory else stack.enter_context(path.open("rb"))
        opened[fd] = path, stream

        def check():
            checked.append(path)
            assert path.lstat().st_ino == info.st_ino

        return SimpleNamespace(fd=fd, info=info, check=check)

    fake_os = SimpleNamespace(
        stat=lambda name, dir_fd, follow_symlinks: (
            (root.parent if dir_fd is None else opened[dir_fd][0]) / name
        ).lstat(),
        fstat=lambda fd: opened[fd][0].lstat(),
        listdir=lambda fd: [p.name for p in opened[fd][0].iterdir()],
        read=lambda fd, size: opened[fd][1].read(size),
    )
    fake_fs = SimpleNamespace(
        _parent=parent, _open=open_entry, _check=lambda chain: [p.check() for p in chain]
    )
    monkeypatch.setattr(repair, "os", fake_os)
    return repair, root, sentinel, fake_fs, fake_os, checked, os


def test_offline_tree_hashes_every_file_preserves_inodes_never_executes_venv(portable_tree):
    repair, root, sentinel, fs, _, checked, _ = portable_tree
    before = {str(p): p.lstat().st_ino for p in [root, *root.rglob("*")]}
    first = repair.snapshot_tree(root, fs=fs)
    second = repair.snapshot_tree(root, fs=fs)
    assert first == second
    assert len(first) == len(before)
    assert all(value["inode"] == before[str(Path(name))] for name, value in first.items())
    assert (
        first[(root / "credentials.env").as_posix()]["sha256"]
        == hashlib.sha256(b"not-a-real-credential").hexdigest()
    )
    assert checked and not sentinel.exists()
    assert before == {str(p): p.lstat().st_ino for p in [root, *root.rglob("*")]}


def test_offline_tree_refuses_hardlinked_file(portable_tree):
    repair, root, _, fs, _, _, os = portable_tree
    os.link(root / "credentials.env", root / "alias")
    with pytest.raises(ValueError, match="links"):
        repair.snapshot_tree(root, fs=fs)


def test_offline_tree_rejects_file_changed_during_hash(portable_tree):
    repair, root, _, fs, fake_os, _, _ = portable_tree
    read = fake_os.read
    changed = []

    def racing_read(fd, size):
        raw = read(fd, size)
        if raw and not changed:
            changed.append(1)
            with (root / "credentials.env").open("ab") as stream:
                stream.write(b"changed")
        return raw

    fake_os.read = racing_read
    with pytest.raises(ValueError, match="changed during read"):
        repair.snapshot_tree(root, fs=fs)


def test_post_install_requires_exact_old_bundle_bytes_metadata_and_inodes(monkeypatch):
    repair = repair_module()
    root = str(repair.LIBEXEC)
    before = {
        "entries": {
            root: dict(kind="directory", uid=0, gid=0, mode=0o755, inode=1, children=["helper.py"]),
            root
            + "/helper.py": dict(kind="file", uid=0, gid=0, mode=0o644, inode=2, sha256="a" * 64),
        }
    }
    retained = "/usr/local/libexec/.knxohui-bundle-random"
    after = {
        "entries": {
            name.replace(root, retained): copy.deepcopy(value)
            for name, value in before["entries"].items()
        }
    }
    after["entries"][retained]["mode"] = 0o700
    monkeypatch.setattr(repair, "_component_files", lambda *a: {})
    monkeypatch.setattr(repair, "_validate_component_bytes", lambda *a: None)
    repair.verify_repaired(None, before, after, None, None)
    for field in ("inode", "mode", "sha256"):
        changed = copy.deepcopy(after)
        changed["entries"][retained + "/helper.py"][field] = "changed"
        with pytest.raises(ValueError, match="previous bundle"):
            repair.verify_repaired(None, before, changed, None, None)
    after["entries"][retained + "-second"] = after["entries"][retained]
    with pytest.raises(ValueError, match="exactly one"):
        repair.verify_repaired(None, before, after, None, None)


def test_guest_program_transports_only_explicit_reviewed_repair(monkeypatch):
    repair = repair_module()
    calls = []
    monkeypatch.setattr(repair, "validate_repair_checkpoint", lambda *a: calls.append("checkpoint"))
    monkeypatch.setattr(repair, "validate_repair_source", lambda *a: calls.append("source"))
    program = runner.guest_program(
        "repair-environmentfile",
        NONCE,
        checkpoint={"old_source_approval": {}},
        source_approval={"head": HEAD},
        approved_head=HEAD,
    )
    assert calls == ["checkpoint", "source"]
    compile(program, "<offline trusted transport>", "exec")
    assert "run_phase('repair-environmentfile'" in program
    assert "<trusted repair boundary>" in program
    assert "resume_after_sudo(EXPECTED_NONCE" not in program


def test_fixture_dispatch_repair_cannot_fall_back_to_bootstrap(monkeypatch):
    repair = repair_module()
    calls = []
    monkeypatch.setattr(repair, "repair_environmentfile", lambda *a, **k: calls.append((a, k)))
    fixture.run_phase(
        "repair-environmentfile", NONCE, checkpoint={}, source_approval={}, approved_head=HEAD
    )
    assert calls == [
        ((fixture, NONCE), dict(checkpoint={}, source_approval={}, approved_head=HEAD))
    ]


@pytest.fixture
def synthetic_sources(monkeypatch):
    repair = repair_module()
    files = {
        name: dict(sha256="a" * 64, mode=0o644)
        for name in (
            "installer/update_bootstrap.py",
            "installer/bootstrap_activation.py",
            "installer/update_core/__init__.py",
            "requirements.txt",
            "VERSION",
        )
    }
    files["requirements.txt"][
        "sha256"
    ] = "836f5d08439f7a536cae171993c199821a95d1face231826a49bb0043a5829fe"
    old = dict(
        format=1,
        purpose="reviewed-sudo-fix-source",
        head=repair.OLD_HEAD,
        production_base="27d106a26c907b7ce05d1880ea25157b1f815e50",
        review_approved=True,
        root="/opt/knxoh-source-" + repair.OLD_HEAD,
        archive_sha256=repair.OLD_ARCHIVE_SHA256,
        files=files,
    )
    # Pin a known synthetic map, rather than bypassing old manifest validation.
    monkeypatch.setattr(
        repair,
        "OLD_FILES_SHA256",
        hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    new = copy.deepcopy(old)
    new.update(
        purpose="reviewed-environmentfile-fix-source",
        head=HEAD,
        production_base=repair.OLD_HEAD,
        root="/opt/knxoh-source-" + HEAD,
    )
    new["files"]["installer/update_bootstrap.py"]["sha256"] = "b" * 64
    return repair, old, new


def test_new_source_approval_uses_exact_named_identity_and_old_pin(synthetic_sources):
    repair, old, new = synthetic_sources
    assert repair.validate_repair_source(new, HEAD, old).as_posix() == new["root"]
    for field, value in (
        ("head", repair.OLD_HEAD),
        ("review_approved", False),
        ("production_base", "0" * 40),
        ("purpose", "reviewed-sudo-fix-source"),
        ("root", "/opt/current"),
        ("format", True),
        ("archive_sha256", "bad"),
    ):
        wrong = copy.deepcopy(new)
        wrong[field] = value
        with pytest.raises(ValueError):
            repair.validate_repair_source(wrong, HEAD, old)
    old["files"]["VERSION"]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="original source"):
        repair.validate_repair_source(new, HEAD, old)


def test_approved_old_and_new_source_rechecked_not_selected_from_head(
    synthetic_sources, monkeypatch
):
    repair, old, new = synthetic_sources
    checked = []
    monkeypatch.setattr(
        state, "verify_source_approval", lambda value, head: checked.append((value, head)) or head
    )
    assert repair.verify_repair_sources({"old_source_approval": old}, new, HEAD) == HEAD
    assert checked[0] == (old, repair.OLD_HEAD)
    assert checked[1][1] == HEAD
    assert checked[1][0]["files"] == new["files"]


@pytest.mark.parametrize("change", ["bytes", "mode", "owner", "extra"])
def test_installed_components_must_equal_renderer_not_only_snapshot(change):
    repair = repair_module()
    root = str(repair.LIBEXEC)
    raw = b"trusted code"
    entry = dict(
        kind="file", uid=0, gid=0, mode=0o644, links=1, sha256=hashlib.sha256(raw).hexdigest()
    )
    inventory = {
        "entries": {
            root: dict(kind="directory", uid=0, gid=0, mode=0o755, children=["helper.py"]),
            root + "/helper.py": entry,
        }
    }
    expected = {root + "/helper.py": (raw, 0o644)}
    repair._validate_component_bytes(inventory, expected)
    if change == "bytes":
        entry["sha256"] = "0" * 64
    elif change == "mode":
        entry["mode"] = 0o666
    elif change == "owner":
        entry["uid"] = 997
    else:
        inventory["entries"][root]["children"].append("unknown.py")
        inventory["entries"][root + "/unknown.py"] = entry
    with pytest.raises(ValueError):
        repair._validate_component_bytes(inventory, expected)


def test_activation_recovery_failure_must_stop_writers_even_if_ui_active(monkeypatch):
    repair = repair_module()
    events = []
    fake = SimpleNamespace(
        require_guest=lambda nonce: None, command=lambda argv: events.append(argv)
    )
    admin = SimpleNamespace(
        activate_services=lambda outcome, command: events.append("production-activate")
    )
    actual = {
        "units": {
            state.UNITS[0]: dict(ActiveState="active", SubState="running"),
            state.UNITS[2]: dict(ActiveState="active"),
            state.UNITS[4]: dict(
                ActiveState="failed", SubState="failed", Result="exit-code", ExecMainStatus="1"
            ),
        },
        "jobs": [],
    }
    monkeypatch.setattr(repair, "manager_state", lambda: actual)
    monkeypatch.setattr(repair, "health", lambda: events.append("health"))
    with pytest.raises(ValueError, match="recovery"):
        repair.activate_repaired(fake, NONCE, admin)
    assert ["/usr/bin/systemctl", "stop", "--", *repair.WRITERS] in events
    assert "health" not in events


def test_install_failure_retains_evidence_without_bootstrap_or_activation(boundary, capsys):
    repair, _, checkpoint, events, admin = boundary
    admin.install_components = lambda *a: (_ for _ in ()).throw(RuntimeError("private detail"))
    with pytest.raises(RuntimeError, match="private detail"):
        repair.repair_environmentfile(fixture, NONCE, checkpoint, {}, HEAD)
    assert "activate" not in events
    output = capsys.readouterr().out
    assert "retain artifacts, no retry: RuntimeError" in output
    assert "private detail" not in output


def test_actual_production_activation_interface_and_health_order(monkeypatch):
    from installer import bootstrap_activation

    repair = repair_module()
    events = []
    fake = SimpleNamespace(
        require_guest=lambda nonce: None, command=lambda argv: events.append(argv)
    )
    actual = {
        "units": {
            state.UNITS[0]: dict(ActiveState="active", SubState="running"),
            state.UNITS[2]: dict(ActiveState="active"),
            state.UNITS[4]: dict(
                ActiveState="active", SubState="exited", Result="success", ExecMainStatus="0"
            ),
        },
        "jobs": [],
    }
    monkeypatch.setattr(repair, "manager_state", lambda: actual)
    monkeypatch.setattr(repair, "health", lambda: events.append("health"))
    repair.activate_repaired(fake, NONCE, bootstrap_activation)
    assert events == [
        ["/usr/bin/systemctl", "daemon-reload"],
        ["/usr/bin/systemctl", "start", state.UNITS[4]],
        ["/usr/bin/systemctl", "restart", state.UNITS[0]],
        ["/usr/bin/systemctl", "is-active", "--quiet", state.UNITS[0]],
        ["/usr/bin/systemctl", "start", state.UNITS[2]],
        ["/usr/bin/systemctl", "is-active", "--quiet", state.UNITS[2]],
        "health",
    ]


def test_manager_collection_is_read_only_normalizes_only_absent_timer_properties(monkeypatch):
    repair = repair_module()
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        if argv[1] == "list-jobs":
            return SimpleNamespace(
                stdout="42 knxohui.service start waiting\n43 unrelated.service start waiting\n"
            )
        props = dict(
            LoadState="loaded",
            ActiveState="inactive",
            SubState="dead",
            MainPID="0",
            Result="success",
            ExecMainStatus="0",
            NRestarts="19",
            UnitFileState="enabled",
        )
        if argv[-1].endswith(".timer"):
            for name in ("MainPID", "ExecMainStatus", "NRestarts"):
                del props[name]
        return SimpleNamespace(stdout="\n".join(k + "=" + v for k, v in props.items()))

    monkeypatch.setattr(repair.subprocess, "run", run)
    value = repair.manager_state()
    assert value["units"][state.UNITS[0]]["NRestarts"] == "19"
    assert value["units"][state.UNITS[2]]["MainPID"] == "0"
    assert value["jobs"] == [["42", state.UNITS[0], "start", "waiting"]]
    assert all(c[1] in ("show", "list-jobs") for c in commands)
    with pytest.raises(ValueError, match="jobs"):
        repair.validate_manager(value)


def test_retained_real_lease_interface_uses_same_inode_inherited_fd_and_unlocks(monkeypatch):
    import sys

    from installer.update_core import secure_fs as fs
    from installer.update_core.state import LifecycleLock

    events = []
    pinned = SimpleNamespace(
        fd=77,
        info=SimpleNamespace(st_dev=1, st_ino=55, st_uid=0, st_gid=0, st_mode=0o600, st_nlink=1),
    )

    @contextmanager
    def parent(self):
        yield None, 12, "knxohui-lifecycle.lock", []

    @contextmanager
    def lease(paths, paths_file, inherited):
        events.append(("admin-inherited", inherited))
        yield inherited

    monkeypatch.setattr(LifecycleLock, "_parent", parent)
    monkeypatch.setattr(fs, "_open", lambda *a, **k: events.append("open-existing") or pinned)
    monkeypatch.setattr(fs, "_check", lambda *a: events.append("pinned"))
    monkeypatch.setitem(
        sys.modules,
        "fcntl",
        SimpleNamespace(
            LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=lambda fd, flags: events.append((fd, flags))
        ),
    )
    admin = SimpleNamespace(Paths=type(fixture.expected_paths()), installer_lease=lease)
    checkpoint = {"inventory": {"entries": {state.LOCK.as_posix(): {"device": 1, "inode": 55}}}}
    with pytest.raises(RuntimeError, match="stop"):
        with fixture.resume_lease(admin, checkpoint):
            events.append("inside")
            raise RuntimeError("stop")
    assert events == [
        "open-existing",
        (77, 6),
        "pinned",
        ("admin-inherited", 77),
        "inside",
        (77, 8),
    ]
    events.clear()
    checkpoint["inventory"]["entries"][state.LOCK.as_posix()]["inode"] = 56
    with pytest.raises(ValueError, match="inode"):
        with fixture.resume_lease(admin, checkpoint):
            pytest.fail("must not acquire/adopt changed lock")
    assert events == ["open-existing"]


def test_installed_collection_refuses_windows_before_any_filesystem_query(monkeypatch):
    repair = repair_module()
    monkeypatch.setattr(repair, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        state, "collect_inventory", lambda **k: pytest.fail("must refuse before inventory")
    )
    with pytest.raises(ValueError, match="nested root"):
        repair.collect_installed()
