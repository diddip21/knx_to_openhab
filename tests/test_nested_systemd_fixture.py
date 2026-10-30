"""Portable phase dispatch tests; never provision or contact a manager."""

import pytest

from scripts import nested_systemd_fixture as fixture


def block_fresh_effects(monkeypatch, effects):
    from contextlib import contextmanager

    from installer import update_bootstrap as admin

    @contextmanager
    def lease(*args, **kwargs):
        effects.append("lease")
        yield 41

    monkeypatch.setattr(admin, "installer_lease", lease)
    monkeypatch.setattr(fixture, "_seed_fresh", lambda *a, **k: effects.append("seed"))
    monkeypatch.setattr(fixture, "_activate", lambda *a, **k: effects.append("activate"))
    monkeypatch.setattr(fixture, "command", lambda *a, **k: effects.append("command"))
    monkeypatch.setattr(fixture, "write_new", lambda *a, **k: effects.append("file"))


@pytest.mark.parametrize("field", ["releases", "current", "config_dir", "data_dir", "backup_dir"])
def test_off_fixture_contract_cannot_reach_hostile_callback(monkeypatch, field):
    from dataclasses import replace
    from pathlib import Path

    calls = []
    harness = type(
        "Harness",
        (),
        {
            "_check_worker_policy": lambda self: None,
            "test_real_migration_child_no_live_state_sudo_or_surviving_writer": lambda self, value: calls.append(
                "hostile"
            ),
        },
    )()
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: harness)
    expected = fixture.expected_paths()
    from installer.update_core import transaction

    monkeypatch.setattr(
        transaction,
        "load_paths",
        lambda path: replace(expected, **{field: Path("/srv/other installation")}),
    )
    monkeypatch.setattr(fixture, "validate_preparation", lambda: calls.append("preparation"))
    monkeypatch.setattr(
        fixture, "validate_probe_roots", lambda *args: calls.append("roots"), raising=False
    )
    with pytest.raises(ValueError, match="fixture paths"):
        fixture.probe("nonce")
    assert calls == []


def test_exact_probe_paths_and_preparation_precede_hostile_callback(monkeypatch):
    from installer.update_core import transaction

    calls = []
    harness = type(
        "Harness",
        (),
        {
            "_check_worker_policy": lambda self: calls.append("policy"),
            "test_real_migration_child_no_live_state_sudo_or_surviving_writer": lambda self, value: calls.append(
                value
            ),
        },
    )()
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: harness)
    expected = fixture.expected_paths()
    monkeypatch.setattr(transaction, "load_paths", lambda path: expected)
    monkeypatch.setattr(
        fixture, "validate_probe_roots", lambda *args: calls.append("roots"), raising=False
    )
    monkeypatch.setattr(fixture, "validate_preparation", lambda: calls.append("preparation"))
    fixture.probe("nonce")
    assert calls == ["roots", "preparation", "policy", ({}, expected)]


def test_unsafe_preparation_refuses_without_hostile_effect(monkeypatch):
    from installer.update_core import transaction

    calls = []
    harness = type(
        "Harness",
        (),
        {
            "_check_worker_policy": lambda self: calls.append("policy"),
            "test_real_migration_child_no_live_state_sudo_or_surviving_writer": lambda self, value: calls.append(
                "hostile"
            ),
        },
    )()
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: harness)
    monkeypatch.setattr(transaction, "load_paths", lambda path: fixture.expected_paths())
    monkeypatch.setattr(fixture, "validate_probe_roots", lambda *args: None, raising=False)
    monkeypatch.setattr(
        fixture,
        "validate_preparation",
        lambda: (_ for _ in ()).throw(ValueError("unsafe preparation")),
    )
    with pytest.raises(ValueError, match="unsafe preparation"):
        fixture.probe("nonce")
    assert calls == []


@pytest.mark.parametrize(
    "artifact",
    [
        "/etc/systemd/system/knxohui.service",
        "/etc/systemd/system/knxohui.service.d",
        "/usr/local/libexec/knx_to_openhab",
        "/etc/knx_to_openhab/paths.env",
        str(fixture.PATHS_FILE),
        "/etc/sudoers.d/knxohui",
        "/etc/tmpfiles.d/knxohui.conf",
        "/usr/local/sbin/knxohui-service-update",
        "/var/lib/knxohupdate-preparation",
        "/etc/systemd/system/multi-user.target.wants/knxohui.service",
    ],
)
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_stale_full_footprint_refuses_before_any_fresh_effect(monkeypatch, artifact, kind):
    effects = []
    inventory = {"entries": {artifact: {"kind": kind}}, "accounts": {}, "groups": {}}
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: None)
    monkeypatch.setattr(fixture, "collect_inventory", lambda **kwargs: inventory)
    block_fresh_effects(monkeypatch, effects)
    with pytest.raises(ValueError, match="Fresh fixture"):
        fixture.bootstrap("nonce")
    assert effects == []


@pytest.mark.parametrize("name", ["knxohui", "knxohupdate"])
def test_group_only_remnant_is_not_adopted(monkeypatch, name):
    effects = []
    inventory = {"entries": {}, "accounts": {}, "groups": {name: {"gid": 989}}}
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: None)
    monkeypatch.setattr(fixture, "collect_inventory", lambda **kwargs: inventory)
    block_fresh_effects(monkeypatch, effects)
    with pytest.raises(ValueError, match="Fresh fixture"):
        fixture.bootstrap("nonce")
    assert effects == []


@pytest.mark.parametrize("unsafe", [None, "uid", "gid", "mode", "type"])
def test_fixed_preparation_checks_opened_metadata(unsafe):
    import stat
    from contextlib import contextmanager
    from types import SimpleNamespace

    from scripts.nested_fixture_state import PREPARATION

    info = SimpleNamespace(st_uid=0, st_gid=988, st_mode=stat.S_IFDIR | 0o750)
    if unsafe == "uid":
        info.st_uid = 999
    elif unsafe == "gid":
        info.st_gid = 989
    elif unsafe == "mode":
        info.st_mode = stat.S_IFDIR | 0o770
    elif unsafe == "type":
        info.st_mode = stat.S_IFLNK | 0o750
    calls = []

    @contextmanager
    def parent(path):
        assert path == PREPARATION
        yield None, 41, "knxohupdate-preparation", ["ancestors"]

    def opened(stack, fd, name, owners, device, directory):
        assert (owners, directory, device) == ({0}, True, 1)
        return SimpleNamespace(info=info)

    fs = SimpleNamespace(
        _parent=parent,
        _open=opened,
        _check=lambda chain: calls.append("pinned"),
        os=SimpleNamespace(fstat=lambda fd: SimpleNamespace(st_dev=1)),
    )
    if unsafe:
        with pytest.raises(ValueError):
            fixture.validate_preparation(fs=fs, worker_gid=988)
        assert calls == []
    else:
        fixture.validate_preparation(fs=fs, worker_gid=988)
        assert calls == ["pinned"]


def test_dangling_footprint_leaf_is_not_followed_or_treated_as_absent():
    import stat
    from types import SimpleNamespace

    from scripts import nested_fixture_state as state

    info = SimpleNamespace(
        st_mode=stat.S_IFLNK | 0o777,
        st_uid=0,
        st_gid=0,
        st_dev=1,
        st_ino=7,
        st_nlink=1,
        st_size=20,
        st_mtime_ns=1,
        st_ctime_ns=2,
    )

    class Dangling:
        def lstat(self):
            return info

        def read_bytes(self):
            raise AssertionError("must not follow a dangling leaf")

    observed = state.entry(Dangling(), details=True)
    with pytest.raises(ValueError, match="Fresh fixture"):
        state.validate_fresh(
            dict(entries={"/etc/systemd/system/knxohui.service": observed}, accounts={}, groups={})
        )


@pytest.mark.parametrize(
    "field,value", [("uid", 999), ("gid", 989), ("mode", 0o666), ("links", 2), ("kind", "other")]
)
def test_existing_lock_is_validated_not_removed(field, value):
    from scripts import nested_fixture_state as state

    lock = dict(kind="file", uid=0, gid=0, mode=0o600, links=1, device=1, inode=55)
    lock[field] = value
    with pytest.raises(ValueError, match="lock"):
        state.validate_fresh(dict(entries={state.LOCK.as_posix(): lock}, accounts={}, groups={}))


def test_probe_can_use_explicit_reviewed_fix_policy_without_old_module_cache(monkeypatch):
    from types import SimpleNamespace

    from installer.update_core import transaction
    from scripts import nested_fixture_repair as repair

    calls = []
    harness = SimpleNamespace(
        _check_worker_policy=lambda: (_ for _ in ()).throw(AssertionError("old policy module")),
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=lambda value: calls.append(
            "hostile"
        ),
    )
    admin = SimpleNamespace(
        check_worker=lambda: calls.append("identity"),
        check_worker_sudo=lambda: calls.append("sudo"),
    )
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: harness)
    monkeypatch.setattr(transaction, "load_paths", lambda path: fixture.expected_paths())
    monkeypatch.setattr(
        fixture, "validate_probe_roots", lambda *args: calls.append("roots"), raising=False
    )
    monkeypatch.setattr(fixture, "validate_preparation", lambda: calls.append("preparation"))
    monkeypatch.setattr(
        repair, "verify_probe_source", lambda *args: calls.append("source") or fixture.SOURCE
    )
    monkeypatch.setattr(fixture, "load_approved_admin", lambda path: admin)
    fixture.probe("nonce", source_approval={}, approved_head="de" * 20)
    assert calls == ["roots", "preparation", "source", "identity", "sudo", "hostile"]


def test_untrusted_installed_root_refuses_before_hostile_callback(monkeypatch):
    from types import SimpleNamespace

    from installer.update_core import transaction

    calls = []
    harness = SimpleNamespace(
        _check_worker_policy=lambda: calls.append("policy"),
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=lambda value: calls.append(
            "hostile"
        ),
    )
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: harness)
    monkeypatch.setattr(transaction, "load_paths", lambda path: fixture.expected_paths())
    monkeypatch.setattr(fixture, "validate_preparation", lambda: calls.append("preparation"))
    monkeypatch.setattr(
        fixture,
        "validate_probe_roots",
        lambda *args: (_ for _ in ()).throw(ValueError("untrusted root")),
        raising=False,
    )
    with pytest.raises(ValueError, match="untrusted root"):
        fixture.probe("nonce")
    assert calls == []


def test_invalid_phase_has_no_guard_or_application_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: calls.append("guard"))
    with pytest.raises(ValueError):
        fixture.run_phase("host-install", "nonce")
    assert calls == []


def test_fixture_refusal_precedes_application_effect(monkeypatch):
    calls = []

    def refuse(nonce):
        raise ValueError("wrong guest")

    monkeypatch.setattr(fixture, "require_guest", refuse)
    monkeypatch.setattr(fixture, "bootstrap", lambda nonce: calls.append("bootstrap"))
    with pytest.raises(ValueError, match="wrong guest"):
        fixture.run_phase("bootstrap", "nonce")
    assert calls == []
