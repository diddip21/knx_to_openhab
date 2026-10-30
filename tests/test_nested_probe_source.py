"""Offline probe contract: historical Git blobs only; never contact a guest."""

import copy
import hashlib
import io
import json
import subprocess
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import nested_fixture_repair as repair
from scripts import nested_systemd_fixture as fixture
from scripts import run_nested_systemd_acceptance as runner

SOURCE_PIN = "90936a02e1fa20d124e427e45bd466957f86f379aa15badd0290bbcdc84cafea"
ARCHIVE_PIN = "cdc7a01174a34bb450d7bcb08ae9718df916e70261b0c20f323d166a9183a4f4"


@pytest.fixture(scope="module")
def source_blobs():
    return git_blobs(repair.REPAIRED_HEAD)


@pytest.fixture(scope="module")
def old_source_blobs():
    return git_blobs(repair.OLD_HEAD)


def git_blobs(head):
    # Reconstruct the public hash-only manifest from the exact historical tree,
    # not ignored private receipts or the current checkout (including CRLF).
    raw = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", head],
        cwd=runner.ROOT,
    )
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        return {
            member.name: (
                archive.extractfile(member).read(),
                0o755 if member.mode & 0o111 else 0o644,
            )
            for member in archive.getmembers()
            if member.isfile()
        }


@pytest.fixture(scope="module")
def reviewed_source(source_blobs):
    files = {
        name: {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}
        for name, (raw, mode) in source_blobs.items()
    }
    approval = dict(
        format=1,
        purpose="reviewed-environmentfile-fix-source",
        head=repair.REPAIRED_HEAD,
        production_base=repair.OLD_HEAD,
        review_approved=True,
        root="/opt/knxoh-source-" + repair.REPAIRED_HEAD,
        archive_sha256=ARCHIVE_PIN,
        files=files,
    )
    assert len(files) == 247
    assert hashlib.sha256(manifest_bytes(approval)).hexdigest() == SOURCE_PIN
    return approval


def manifest_bytes(approval):
    return (json.dumps(approval, indent=2, sort_keys=True) + "\n").encode()


def test_reported_repaired_source_generates_probe_without_relabeling(reviewed_source):
    before = copy.deepcopy(reviewed_source)
    program = runner.guest_program(
        "probe", "0" * 64, source_approval=reviewed_source, approved_head=repair.REPAIRED_HEAD
    )
    assert "probe(EXPECTED_NONCE,source_approval=" in program
    assert reviewed_source == before


def forbidden(*args, **kwargs):
    raise AssertionError("Registration, transport or hostile effect reached")


@pytest.fixture
def guest_boundary(monkeypatch, source_blobs, old_source_blobs):
    """Use the real manifest and hash verifier over an in-memory POSIX tree."""
    import stat

    from installer.update_core import secure_fs as fs
    from installer.update_core import transaction

    events = []
    root = Path("/opt/knxoh-source-" + repair.REPAIRED_HEAD)
    old_root = Path("/opt/knxoh-source-" + repair.OLD_HEAD)
    trees = {root: source_blobs, old_root: old_source_blobs}
    directories, files = set(trees), {}
    for tree, blobs in trees.items():
        for name, blob in blobs.items():
            directories.update(p for p in (tree / name).parents if p == tree or tree in p.parents)
            files[tree / name] = blob
    paths = sorted(directories | set(files))

    @contextmanager
    def parent(path):
        assert path in trees
        yield None, 1, path.name, []

    def metadata(path):
        assert path in paths
        mode = stat.S_IFDIR | 0o755 if path in directories else (stat.S_IFREG | files[path][1])
        return SimpleNamespace(st_uid=0, st_gid=0, st_mode=mode)

    contents = {name: raw for name, (raw, _) in source_blobs.items()}
    contents.update({"baseline/" + name: raw for name, (raw, _) in old_source_blobs.items()})

    def read(path, limit):
        events.append("read")
        if old_root in path.parents:
            return contents["baseline/" + path.relative_to(old_root).as_posix()]
        return contents[path.relative_to(root).as_posix()]

    monkeypatch.setattr(fs, "_parent", parent)
    monkeypatch.setattr(fs, "_tree", lambda *a: [])
    monkeypatch.setattr(fs, "_check", lambda *a: None)
    monkeypatch.setattr(fs, "read_regular", read)
    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(
        Path, "rglob", lambda path, pattern: iter(p for p in paths if path in p.parents)
    )
    harness = SimpleNamespace(
        _check_worker_policy=forbidden,
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=lambda value: events.append(
            "hostile"
        ),
    )
    monkeypatch.setattr(fixture, "require_guest", lambda nonce: events.append("guest") or harness)
    monkeypatch.setattr(transaction, "load_paths", lambda path: fixture.expected_paths())
    monkeypatch.setattr(fixture, "validate_probe_roots", lambda paths: events.append("roots"))
    monkeypatch.setattr(fixture, "validate_preparation", lambda: events.append("preparation"))

    def admin(path):
        assert path == root
        events.append("admin")
        return SimpleNamespace(
            check_worker=lambda: events.append("worker"),
            check_worker_sudo=lambda: events.append("sudo"),
        )

    monkeypatch.setattr(fixture, "load_approved_admin", admin)
    monkeypatch.setattr(fixture, "command", forbidden)
    monkeypatch.setattr(fixture, "write_new", forbidden)
    return events, contents


def test_guest_accepts_same_unchanged_source_after_all_guards(
    reviewed_source, old_source_blobs, guest_boundary
):
    before = copy.deepcopy(reviewed_source)
    events, _ = guest_boundary
    fixture.probe("offline", reviewed_source, repair.REPAIRED_HEAD)
    assert events[:3] == ["guest", "roots", "preparation"]
    assert events[3:-4] == ["read"] * (len(old_source_blobs) + len(reviewed_source["files"]) + 2)
    assert events[-4:] == ["admin", "worker", "sudo", "hostile"]
    assert reviewed_source == before


INVALID_SELECTIONS = [
    "purpose",
    "legacy-purpose",
    "base",
    "head",
    "short-head",
    "full-runner-head",
    "unrelated-delta",
    "allowed-but-unreviewed-blob",
    "mode",
    "extra",
    "deleted",
    "archive",
    "review",
]


def invalid_selection(approval, case):
    approval = copy.deepcopy(approval)
    head = repair.REPAIRED_HEAD
    if case in ("purpose", "legacy-purpose"):
        approval["purpose"] = "unreviewed" if case == "purpose" else "reviewed-sudo-fix-source"
    elif case == "base":
        approval["production_base"] = "27d106a26c907b7ce05d1880ea25157b1f815e50"
    elif case == "head":
        approval["head"] = "ab" * 20
    elif case == "short-head":
        head = head[:7]
    elif case == "full-runner-head":
        head = "9f3731c0de31099f091b6d784aab9b2ae84cffa4"
        approval.update(head=head, root="/opt/knxoh-source-" + head)
    elif case in ("unrelated-delta", "allowed-but-unreviewed-blob"):
        name = "VERSION" if case == "unrelated-delta" else "installer/update_bootstrap.py"
        approval["files"][name]["sha256"] = "00" * 32
    elif case == "mode":
        approval["files"]["installer/update_bootstrap.py"]["mode"] = 0o755
    elif case == "extra":
        approval["files"]["unrelated.py"] = {"sha256": "00" * 32, "mode": 0o644}
    elif case == "deleted":
        del approval["files"]["VERSION"]
    elif case == "archive":
        approval["archive_sha256"] = "00" * 32
    else:
        approval["review_approved"] = 1
    return approval, head


@pytest.mark.parametrize("case", [*INVALID_SELECTIONS, "source-pin"])
def test_invalid_source_refused_before_host_registration_or_transport(
    reviewed_source, monkeypatch, tmp_path, case
):
    approval, head = (
        (reviewed_source, repair.REPAIRED_HEAD)
        if case == "source-pin"
        else invalid_selection(reviewed_source, case)
    )
    path = tmp_path / "source.json"
    raw = manifest_bytes(approval)
    path.write_bytes(raw)
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}")
    monkeypatch.setattr(runner.provider, "decode_receipt", lambda raw: {"nonce": "offline"})
    monkeypatch.setattr(runner.provider, "validate_receipt", lambda value: None)
    monkeypatch.setattr(runner.provider, "registration", forbidden)
    monkeypatch.setattr(runner.provider, "preflight", forbidden)
    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    evidence = tmp_path / "absent-evidence"
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "runner",
            "--phase",
            "probe",
            "--receipt",
            str(receipt),
            "--source-approval",
            str(path),
            "--source-approval-sha256",
            "00" * 32 if case == "source-pin" else hashlib.sha256(raw).hexdigest(),
            "--approved-source-head",
            head,
            "--evidence-dir",
            str(evidence),
        ],
    )
    with pytest.raises(ValueError):
        runner.main()
    assert not evidence.exists()


@pytest.mark.parametrize("case", INVALID_SELECTIONS)
def test_guest_agrees_on_invalid_source_before_loading_worker_or_hostile_effects(
    reviewed_source, guest_boundary, case
):
    approval, head = invalid_selection(reviewed_source, case)
    events, _ = guest_boundary
    with pytest.raises(ValueError):
        fixture.probe("offline", approval, head)
    assert events == ["guest", "roots", "preparation"]


@pytest.mark.parametrize("prefix", ["", "baseline/"])
def test_tampered_guest_file_refused_by_real_hash_check_before_worker(
    reviewed_source, guest_boundary, prefix
):
    events, contents = guest_boundary
    contents[prefix + "installer/update_bootstrap.py"] = b"tampered"
    with pytest.raises(ValueError, match="file hash mismatch"):
        fixture.probe("offline", reviewed_source, repair.REPAIRED_HEAD)
    assert "read" in events
    assert not {"admin", "worker", "sudo", "hostile"} & set(events)


def test_generated_probe_ships_current_shared_repair_parser(reviewed_source):
    import ast
    import types

    program = runner.guest_program(
        "probe", "0" * 64, source_approval=reviewed_source, approved_head=repair.REPAIRED_HEAD
    )
    payloads = [
        node.args[0].value
        for node in ast.walk(ast.parse(program))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "compile"
    ]
    assert payloads[-1] == (runner.ROOT / "scripts/nested_fixture_repair.py").read_text("utf-8")
    module = types.ModuleType("offline_shared_repair")
    exec(compile(payloads[-1], "<offline shared parser>", "exec"), module.__dict__)
    assert module.validate_probe_source(reviewed_source, repair.REPAIRED_HEAD) == Path(
        reviewed_source["root"]
    )


def test_repaired_probe_reuses_canonical_baseline_and_delta_parser(reviewed_source, monkeypatch):
    calls = []
    canonical = repair.validate_repair_source

    def checked(approval, head, old):
        calls.append(old)
        return canonical(approval, head, old)

    monkeypatch.setattr(repair, "validate_repair_source", checked)
    repair.validate_probe_source(reviewed_source, repair.REPAIRED_HEAD)
    assert len(calls) == 1
    assert calls[0]["head"] == repair.OLD_HEAD
    assert repair.validate_old_source(calls[0]) == Path(calls[0]["root"])


def test_guest_reuses_existing_repair_verifier_including_baseline_blobs(
    reviewed_source, monkeypatch
):
    calls = []

    def verified(source_pair, approval, head):
        repair.validate_old_source(source_pair["old_source_approval"])
        assert approval == reviewed_source and head == repair.REPAIRED_HEAD
        calls.append("canonical-verifier")
        return Path(approval["root"])

    monkeypatch.setattr(repair, "verify_repair_sources", verified)
    monkeypatch.setattr(repair.state, "verify_source_approval", forbidden)
    assert repair.verify_probe_source(reviewed_source, repair.REPAIRED_HEAD) == Path(
        reviewed_source["root"]
    )
    assert calls == ["canonical-verifier"]


@pytest.mark.parametrize("guard", ["guest", "roots", "preparation", "worker", "sudo"])
def test_repaired_probe_preserves_all_guard_refusals(
    reviewed_source, guest_boundary, monkeypatch, guard
):
    events, _ = guest_boundary

    def refuse(*args):
        raise ValueError("guard refused")

    if guard in ("guest", "roots", "preparation"):
        name = {
            "guest": "require_guest",
            "roots": "validate_probe_roots",
            "preparation": "validate_preparation",
        }[guard]
        monkeypatch.setattr(fixture, name, refuse)
    else:
        admin = SimpleNamespace(
            check_worker=refuse if guard == "worker" else lambda: None, check_worker_sudo=refuse
        )
        monkeypatch.setattr(fixture, "load_approved_admin", lambda path: admin)
    with pytest.raises(ValueError, match="guard refused"):
        fixture.probe("offline", reviewed_source, repair.REPAIRED_HEAD)
    assert "hostile" not in events


def test_legacy_probe_selection_keeps_original_strict_parser(reviewed_source):
    from scripts import nested_fixture_state as state

    legacy = copy.deepcopy(reviewed_source)
    legacy.update(
        purpose="reviewed-sudo-fix-source",
        production_base="27d106a26c907b7ce05d1880ea25157b1f815e50",
        head=repair.OLD_HEAD,
        root="/opt/knxoh-source-" + repair.OLD_HEAD,
        archive_sha256=repair.OLD_ARCHIVE_SHA256,
        files={
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}
            for name, (raw, mode) in git_blobs(repair.OLD_HEAD).items()
        },
    )
    assert repair.validate_probe_source(legacy, repair.OLD_HEAD) == (
        state.validate_source_manifest(legacy, repair.OLD_HEAD)
    )
    repair.validate_old_source(legacy)
    legacy["files"]["requirements.txt"]["sha256"] = "00" * 32
    with pytest.raises(ValueError, match="dependency contract"):
        repair.validate_probe_source(legacy, repair.OLD_HEAD)
