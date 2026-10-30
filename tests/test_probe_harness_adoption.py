"""Portable adoption checks; no guest, manager, candidate or real callback."""

import copy
import hashlib
import io
import json
import stat
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import probe_harness_adoption as adoption
from scripts import run_nested_systemd_acceptance as runner


@pytest.fixture(scope="module")
def approval():
    raw = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", adoption.HEAD],
        cwd=runner.ROOT,
    )
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        files = {
            m.name: {
                "sha256": hashlib.sha256(archive.extractfile(m).read()).hexdigest(),
                "mode": 0o755 if m.mode & 0o111 else 0o644,
            }
            for m in archive
            if m.isfile()
        }
    assert hashlib.sha256(raw).hexdigest() == adoption.ARCHIVE_SHA256
    return dict(
        format=1,
        purpose="probe-only-reviewed-harness",
        head=adoption.HEAD,
        root=adoption.HARNESS.as_posix(),
        archive_sha256=adoption.ARCHIVE_SHA256,
        review_approved=True,
        files=files,
    )


def test_exact_historical_inventory(approval):
    assert adoption.validate_approval(approval) == adoption.HARNESS
    assert len(approval["files"]) == 269


def test_real_source_pin_and_early_fresh_dispatch(approval):
    raw = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", adoption.SOURCE_HEAD]
    )
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        files = {
            m.name: {
                "sha256": hashlib.sha256(archive.extractfile(m).read()).hexdigest(),
                "mode": 0o755 if m.mode & 0o111 else 0o644,
            }
            for m in archive
            if m.isfile()
        }
    source = dict(
        format=1,
        purpose="reviewed-environmentfile-fix-source",
        head=adoption.SOURCE_HEAD,
        production_base="47e2c3a3cd59d716f793226ec17badde60999eca",
        review_approved=True,
        root="/opt/knxoh-source-" + adoption.SOURCE_HEAD,
        archive_sha256="cdc7a01174a34bb450d7bcb08ae9718df916e70261b0c20f323d166a9183a4f4",
        files=files,
    )
    assert {k: v for k, v in approval["files"].items() if k.startswith("installer/")} == {
        k: v for k, v in source["files"].items() if k.startswith("installer/")
    }
    adoption.validate_source(source, adoption.SOURCE_HEAD)
    program = runner.guest_program(
        "probe",
        "offline",
        harness_approval=approval,
        source_approval=source,
        approved_head=adoption.SOURCE_HEAD,
    )
    assert "/opt/knxoh-harness-d1f1848" not in program
    assert "require_guest(EXPECTED_NONCE)" not in program
    assert "types.ModuleType" not in program
    assert "sys.modules[module.__name__]=module" not in program
    assert "run_probe('offline'" in program
    assert "<separately pinned probe dispatcher>" in program


@pytest.mark.parametrize("field", ["head", "root", "archive_sha256", "purpose", "files"])
def test_wrong_tree_rejected(approval, field):
    bad = copy.deepcopy(approval)
    if field == "files":
        bad[field]["VERSION"]["sha256"] = "00" * 32
    else:
        bad[field] = "wrong"
    with pytest.raises(ValueError):
        adoption.validate_approval(bad)


def test_selection_precedes_any_old_import_and_requires_source(approval):
    with pytest.raises(ValueError):
        runner.guest_program("probe", "offline", harness_approval=approval)
    with pytest.raises(ValueError):
        runner.guest_program("bootstrap", "offline", harness_approval=approval)


@pytest.mark.parametrize("name", ["installer", "scripts", "test_update_systemd"])
def test_cached_trusted_import_refused(name):
    with pytest.raises(ValueError, match="cached"):
        adoption.refuse_cached_modules({name: SimpleNamespace(__file__="old")})


@pytest.mark.parametrize("origin", ["module", "callback", "adapter"])
def test_actual_origin_not_only_selection_checked(approval, origin):
    callback_path = adoption.HARNESS / "tests/integration/test_update_systemd.py"
    adapter_path = adoption.HARNESS / "installer/update_core/systemd.py"
    callback = SimpleNamespace(__code__=SimpleNamespace(co_filename=str(callback_path)))
    module = SimpleNamespace(
        __file__=str(callback_path),
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=callback,
        SystemdAdapter=SimpleNamespace(
            __init__=SimpleNamespace(__code__=SimpleNamespace(co_filename=str(adapter_path)))
        ),
    )
    modules = {"test_update_systemd": module}
    if origin == "module":
        module.__file__ = "/opt/knxoh-harness-d1f1848/tests/integration/test_update_systemd.py"
    elif origin == "callback":
        callback.__code__.co_filename = "<cached callback>"
    else:
        module.SystemdAdapter.__init__.__code__.co_filename = "<wrong adapter>"
    with pytest.raises(ValueError, match="origin"):
        adoption.verify_origins(approval, module, modules)


def test_host_bad_pin_refused_before_transport(approval, monkeypatch, tmp_path):
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval))
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "runner",
            "--phase",
            "probe",
            "--receipt",
            str(tmp_path / "missing"),
            "--evidence-dir",
            str(tmp_path / "absent"),
            "--probe-harness-approval",
            str(path),
            "--probe-harness-approval-sha256",
            "00" * 32,
        ],
    )
    monkeypatch.setattr(runner.provider, "registration", lambda: pytest.fail("transport"))
    with pytest.raises(ValueError, match="pin"):
        runner.main()
    assert not (tmp_path / "absent").exists()


@pytest.fixture
def tree(approval, monkeypatch):
    raw = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", adoption.HEAD]
    )
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        contents = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
    root = adoption.HARNESS
    entries = {p: (stat.S_IFDIR | 0o755, 0, 0, 1) for p in (root, *root.parents)}
    for name, value in approval["files"].items():
        path = root / name
        entries[path] = (stat.S_IFREG | value["mode"], 0, 0, 1)
        for parent in path.parents:
            entries.setdefault(parent, (stat.S_IFDIR | 0o755, 0, 0, 1))

    def metadata(path):
        mode, uid, gid, links = entries[path]
        return SimpleNamespace(
            st_mode=mode,
            st_uid=uid,
            st_gid=gid,
            st_nlink=links,
            st_dev=1,
            st_ino=abs(hash(path)),
            st_size=0,
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(
        Path, "iterdir", lambda path: iter(p for p in entries if p.parent == path and p != path)
    )
    monkeypatch.setattr(
        adoption, "read_file", lambda path: contents[path.relative_to(root).as_posix()]
    )
    return entries, contents


def test_real_tree_verifier_accepts_full_inventory(approval, tree):
    assert adoption.verify_tree(approval) == adoption.HARNESS


@pytest.mark.parametrize(
    "case", ["callback", "adapter", "extra", "symlink", "hardlink", "owner", "ancestor", "missing"]
)
def test_guest_tree_refusal_has_zero_imports_or_effects(approval, tree, monkeypatch, case):
    entries, contents = tree
    target = adoption.HARNESS / adoption.CALLBACK
    if case in ("callback", "adapter"):
        contents[adoption.CALLBACK if case == "callback" else adoption.ADAPTER] = b"wrong"
    elif case == "extra":
        entries[adoption.HARNESS / "unexpected.py"] = (stat.S_IFREG | 0o644, 0, 0, 1)
    elif case == "missing":
        del entries[target]
    else:
        entries[target if case != "ancestor" else adoption.HARNESS.parent] = {
            "symlink": (stat.S_IFLNK | 0o777, 0, 0, 1),
            "hardlink": (stat.S_IFREG | 0o644, 0, 0, 2),
            "owner": (stat.S_IFREG | 0o644, 999, 0, 1),
            "ancestor": (stat.S_IFDIR | 0o777, 0, 0, 1),
        }[case]
    monkeypatch.setattr(adoption, "validate_source", lambda *a: None)
    monkeypatch.setattr(adoption, "sys", SimpleNamespace(modules={}))
    monkeypatch.setattr(
        adoption.importlib, "import_module", lambda *a: pytest.fail("import/effect")
    )
    with pytest.raises(ValueError):
        adoption.run_probe("offline", approval, {}, adoption.SOURCE_HEAD)


def test_wrong_source_has_zero_tree_or_import_effects(approval, monkeypatch):
    monkeypatch.setattr(adoption, "verify_tree", lambda *a: pytest.fail("tree/import/effect"))
    with pytest.raises(ValueError, match="production"):
        adoption.run_probe("offline", approval, {}, adoption.SOURCE_HEAD)


@pytest.mark.parametrize(
    "refusal", [None, "provider", "paths", "preparation", "source", "worker", "sudo", "helper"]
)
def test_selected_probe_only_reaches_spy_after_guards(approval, tree, monkeypatch, refusal):
    from installer.update_core import secure_fs as fs

    events = []

    def guard(name, result=None):
        def call(*args):
            events.append(name)
            if refusal == name:
                raise ValueError("guard refused")
            return result

        return call

    class CallbackSpy:
        __code__ = SimpleNamespace(co_filename=str(adoption.HARNESS / adoption.CALLBACK))

        def __call__(self, value):
            guard("callback")(value)

    callback = CallbackSpy()
    # Real Python callback code is never executed: the spy is deliberately local.
    harness = SimpleNamespace(
        __file__=str(adoption.HARNESS / adoption.CALLBACK),
        SystemdAdapter=SimpleNamespace(
            __init__=SimpleNamespace(
                __code__=SimpleNamespace(co_filename=str(adoption.HARNESS / adoption.ADAPTER))
            )
        ),
        _check_virtualization=guard("provider"),
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=callback,
    )
    admin = SimpleNamespace(
        BUNDLE=("update_prepare.py",), check_worker=guard("worker"), check_worker_sudo=guard("sudo")
    )
    fixture = SimpleNamespace(
        PATHS_FILE="paths",
        expected_paths=lambda: "paths",
        validate_probe_roots=guard("paths"),
        validate_preparation=guard("preparation"),
        load_approved_admin=guard("admin", admin),
    )
    repair = SimpleNamespace(MACHINE_ID="machine", verify_probe_source=guard("source", "source"))
    modules = {
        "test_update_systemd": harness,
        "scripts.nested_systemd_fixture": fixture,
        "scripts.nested_fixture_repair": repair,
        "installer.update_core.transaction": SimpleNamespace(load_paths=lambda p: "paths"),
    }
    for name, module in modules.items():
        if name != "test_update_systemd":
            module.__file__ = str(adoption.HARNESS / (name.replace(".", "/") + ".py"))
    monkeypatch.setattr(adoption, "validate_source", lambda *a: None)
    real_tree, real_origins = adoption.verify_tree, adoption.verify_origins

    def verified_tree(value):
        events.append("tree")
        return real_tree(value)

    def verified_origins(*args):
        events.append("origins")
        return real_origins(*args)

    monkeypatch.setattr(adoption, "verify_tree", verified_tree)
    monkeypatch.setattr(adoption, "verify_origins", verified_origins)
    monkeypatch.setattr(adoption, "verify_admin_origins", guard("admin-origins"))
    monkeypatch.setattr(adoption, "sys", SimpleNamespace(modules={}, path=[]))
    monkeypatch.setattr(adoption, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))

    def imported(name):
        adoption.sys.modules[name] = modules[name]
        return modules[name]

    monkeypatch.setattr(adoption.importlib, "import_module", imported)
    monkeypatch.setattr(Path, "read_text", lambda *a: "machine")
    monkeypatch.setattr(fs, "read_regular", guard("helper", b"verified helper"))
    source = {
        "files": {
            "installer/update_prepare.py": {
                "sha256": hashlib.sha256(b"verified helper").hexdigest()
            }
        }
    }
    if refusal:
        with pytest.raises(ValueError, match="guard refused"):
            adoption.run_probe("offline", approval, source, adoption.SOURCE_HEAD)
        assert "callback" not in events
    else:
        adoption.run_probe("offline", approval, source, adoption.SOURCE_HEAD)
        assert events == [
            "tree",
            "origins",
            "provider",
            "paths",
            "preparation",
            "source",
            "admin",
            "admin-origins",
            "helper",
            "worker",
            "sudo",
            "origins",
            "callback",
        ]
