"""Synthetic/read-only boundary tests, never contact a manager or guest."""

import copy
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import nested_fixture_state as state
from scripts import nested_systemd_fixture as fixture

NONCE = "ab" * 32
HEAD = "de" * 20


@pytest.fixture
def recorded():
    entries = copy.deepcopy(state.recorded_specs(NONCE))
    for index, entry in enumerate(entries.values(), 1):
        entry.update(device=1, inode=index)
        entry.setdefault("links", 2)
    return dict(
        entries=entries,
        hostname="localhost",
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


@pytest.fixture
def resume_boundary(monkeypatch, recorded):
    effects, queries = [], []
    checkpoint = state.checkpoint_candidate(copy.deepcopy(recorded), NONCE)
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: queries.append("guest"))
    monkeypatch.setattr(fixture, "collect_inventory", lambda **kwargs: copy.deepcopy(recorded))
    monkeypatch.setattr(
        fixture,
        "verify_source_approval",
        lambda value, head: queries.append("source") or fixture.SOURCE,
        raising=False,
    )
    admin = SimpleNamespace(
        Paths=type(fixture.expected_paths()),
        check_worker=lambda: queries.append("worker") or "worker-account",
        check_worker_sudo=lambda: queries.append("sudo"),
        provision_state=lambda *args: effects.append("state"),
        install_components=lambda *args: effects.append("bundle"),
    )
    monkeypatch.setattr(fixture, "load_approved_admin", lambda root: admin, raising=False)

    @contextmanager
    def lease(admin, checkpoint):
        queries.append("lease-enter")
        yield
        queries.append("lease-exit")

    monkeypatch.setattr(fixture, "resume_lease", lease, raising=False)
    monkeypatch.setattr(
        fixture, "_prepare_initial", lambda *args: effects.append("prepare"), raising=False
    )
    monkeypatch.setattr(
        fixture, "_activate", lambda *args: effects.append("activate"), raising=False
    )
    return recorded, checkpoint, effects, queries, admin


@pytest.mark.parametrize(
    "changed",
    [
        "hash",
        "mode",
        "uid",
        "gid",
        "memberships",
        "alias",
        "extra",
        "current",
        "hostname",
        "receipt",
        "inode",
        "children",
        "symlink",
        "nonce",
        "prep",
        "default-contract",
    ],
)
def test_changed_partial_checkpoint_cannot_reach_provisioning(resume_boundary, changed):
    observed, checkpoint, effects, queries, _ = resume_boundary
    entry = observed["entries"][(state.CONFIG / "config.json").as_posix()]
    if changed in ("hash", "mode", "uid", "gid", "inode"):
        key = {"hash": "sha256"}.get(changed, changed)
        entry[key] = "00" * 32 if changed == "hash" else 12345
    elif changed == "memberships":
        observed["accounts"]["knxohupdate"]["groups"].append(27)
    elif changed == "alias":
        observed["aliases"]["knxohupdate"].append("sudo")
    elif changed in ("extra", "current"):
        observed["entries"][
            str(state.BASE / ("unknown" if changed == "extra" else "current"))
        ] = entry
    elif changed == "hostname":
        observed["hostname"] = "other"
    elif changed == "children":
        observed["entries"][state.CONFIG.as_posix()]["children"].append("unknown.json")
    elif changed == "symlink":
        entry["kind"] = "other"
    elif changed == "nonce":
        checkpoint["nonce"] = "cd" * 32
    elif changed in ("prep", "default-contract"):
        path = (
            state.PREPARATION.as_posix() if changed == "prep" else "/etc/knx_to_openhab/paths.env"
        )
        observed["entries"][path] = entry
    else:
        observed["entries"][state.RECEIPT.as_posix()]["sha256"] = "00" * 32
    with pytest.raises(ValueError):
        fixture.resume_after_sudo(NONCE, checkpoint, {}, HEAD)
    assert effects == []
    assert "source" not in queries


def test_exact_partial_runs_only_tail_under_retained_lease(resume_boundary):
    _, checkpoint, effects, queries, _ = resume_boundary
    fixture.resume_after_sudo(NONCE, checkpoint, {}, HEAD)
    assert effects == ["state", "bundle", "prepare", "activate"]
    assert queries == [
        "guest",
        "source",
        "lease-enter",
        "guest",
        "source",
        "worker",
        "sudo",
        "lease-exit",
    ]


def test_under_lease_checkpoint_change_still_has_zero_provisioning_effects(
    resume_boundary, monkeypatch
):
    recorded, checkpoint, effects, _, _ = resume_boundary
    calls = []

    def inventory(**kwargs):
        value = copy.deepcopy(recorded)
        calls.append(1)
        if len(calls) == 2:
            value["entries"][state.LOCK.as_posix()]["inode"] += 1
        return value

    monkeypatch.setattr(fixture, "collect_inventory", inventory)
    with pytest.raises(ValueError):
        fixture.resume_after_sudo(NONCE, checkpoint, {}, HEAD)
    assert effects == []


def test_source_refusal_precedes_all_provisioning(resume_boundary, monkeypatch):
    _, checkpoint, effects, _, _ = resume_boundary
    monkeypatch.setattr(
        fixture,
        "verify_source_approval",
        lambda *args: (_ for _ in ()).throw(ValueError("unreviewed source")),
    )
    with pytest.raises(ValueError, match="unreviewed source"):
        fixture.resume_after_sudo(NONCE, checkpoint, {}, HEAD)
    assert effects == []


def test_real_sudo_recheck_refusal_has_no_tail_effects(resume_boundary):
    _, checkpoint, effects, _, admin = resume_boundary
    admin.check_worker_sudo = lambda: (_ for _ in ()).throw(ValueError("policy unavailable"))
    with pytest.raises(ValueError, match="policy unavailable"):
        fixture.resume_after_sudo(NONCE, checkpoint, {}, HEAD)
    assert effects == []


def test_standalone_administrator_uses_its_own_protocol_class():
    class StandalonePaths:
        def __init__(self, *values):
            self.values = values

    paths = fixture.admin_paths(SimpleNamespace(Paths=StandalonePaths))
    assert type(paths) is StandalonePaths
    assert paths.values == (
        fixture.BASE / "releases",
        fixture.BASE / "current",
        fixture.CONFIG,
        fixture.DATA,
        fixture.BACKUPS,
    )
