"""Offline deployment regressions; never contact WSL or a service manager."""

import copy
import hashlib
import io
import json
import stat
import subprocess
import tarfile
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from scripts import deploy_probe_harness as deploy


@pytest.fixture(scope="module")
def inputs():
    deploy.ADOPTION_SOURCE = (Path(deploy.__file__).parent / "probe_harness_adoption.py").read_text(
        encoding="utf-8"
    )
    raw = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", deploy.HEAD]
    )
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        files = {
            m.name: dict(
                sha256=hashlib.sha256(archive.extractfile(m).read()).hexdigest(),
                mode=m.mode & 0o755,
            )
            for m in archive
            if m.isfile()
        }
    approval = dict(
        format=1,
        purpose="probe-only-reviewed-harness",
        head=deploy.HEAD,
        root=deploy.TARGET,
        archive_sha256=deploy.ARCHIVE_SHA,
        review_approved=True,
        files=files,
    )
    return raw, approval


def test_fixed_native_archive_full_map(inputs):
    raw, approval = inputs
    contents = deploy.check_archive(raw, approval)
    assert len(contents) == 269
    assert contents["tests/integration/test_update_systemd.py"][1] == 0o644


@pytest.mark.parametrize("case", ["bytes", "map", "root", "missing", "mode"])
def test_bad_inputs_before_any_destination_effect(inputs, monkeypatch, case):
    raw, approval = inputs
    approval = copy.deepcopy(approval)
    if case == "bytes":
        raw += b"bad"
    elif case == "root":
        approval["root"] += "-other"
    elif case == "missing":
        approval["files"].pop("VERSION")
    elif case == "mode":
        approval["files"]["VERSION"]["mode"] = 0o777
    else:
        approval["files"]["VERSION"]["sha256"] = "00" * 32
    monkeypatch.setattr(deploy, "old_guard", lambda *a: pytest.fail("guard/import"))
    monkeypatch.setattr(deploy, "extract_new", lambda *a: pytest.fail("write"))
    with pytest.raises(ValueError):
        deploy.guest_deploy(raw, approval, {})


@pytest.mark.parametrize(
    "name,kind,mode,uid",
    [
        ("../escape", tarfile.REGTYPE, 0o664, 0),
        ("/escape", tarfile.REGTYPE, 0o664, 0),
        ("a\\b", tarfile.REGTYPE, 0o664, 0),
        ("a//b", tarfile.REGTYPE, 0o664, 0),
        ("./a", tarfile.REGTYPE, 0o664, 0),
        (".", tarfile.REGTYPE, 0o664, 0),
        ("a", tarfile.SYMTYPE, 0o664, 0),
        ("a", tarfile.LNKTYPE, 0o664, 0),
        ("a", tarfile.FIFOTYPE, 0o664, 0),
        ("a", tarfile.REGTYPE, 0o4664, 0),
        ("a", tarfile.REGTYPE, 0o664, 1),
    ],
)
def test_archive_header_refusals(name, kind, mode, uid):
    member = tarfile.TarInfo(name)
    member.type, member.mode, member.uid = kind, mode, uid
    with pytest.raises(ValueError):
        deploy.check_member(member, set())


def test_duplicate_member_refused():
    member = tarfile.TarInfo("VERSION")
    member.mode = 0o664
    with pytest.raises(ValueError, match="member"):
        deploy.check_member(member, {"VERSION"})


def test_original_guard_refusal_precedes_writes_and_new_import(inputs, monkeypatch):
    raw, approval = inputs
    events = []

    def refused(*args):
        events.append("old-guard")
        raise ValueError("original guard refused")

    monkeypatch.setattr(deploy, "old_guard", refused)
    monkeypatch.setattr(deploy, "extract_new", lambda *a: pytest.fail("write"))
    monkeypatch.setattr(deploy.importlib, "import_module", lambda *a: pytest.fail("import"))
    with pytest.raises(ValueError, match="original guard"):
        deploy.guest_deploy(raw, approval, {})
    assert events == ["old-guard"]


def test_no_new_import_even_after_successful_deployment(inputs, monkeypatch):
    raw, approval = inputs
    events = []
    monkeypatch.setattr(deploy, "old_guard", lambda *a: events.append("old-guard"))
    monkeypatch.setattr(deploy, "extract_new", lambda *a: events.append("extract"))
    monkeypatch.setattr(deploy, "verify_deployed", lambda *a: events.append("full-inventory"))
    monkeypatch.setattr(deploy.importlib, "import_module", lambda *a: pytest.fail("import"))
    deploy.guest_deploy(raw, approval, {})
    assert events == ["old-guard", "extract", "full-inventory"]


def test_bad_external_approval_pin_before_registration(tmp_path, monkeypatch):
    approval = tmp_path / "approval.json"
    approval.write_text("{}")
    monkeypatch.setattr(
        deploy.sys,
        "argv",
        [
            "deploy",
            "--archive",
            str(tmp_path / "absent.tar"),
            "--approval",
            str(approval),
            "--approval-sha256",
            "00" * 32,
            "--operator-sha256",
            "00" * 32,
            "--receipt",
            str(tmp_path / "absent.json"),
            "--evidence-dir",
            str(tmp_path / "out"),
        ],
    )
    monkeypatch.setattr(deploy, "load_provider", lambda: pytest.fail("registration"))
    with pytest.raises(ValueError, match="pin"):
        deploy.main()
    assert not (tmp_path / "out").exists()


class FakeFDs:
    """Small POSIX FD model: asserts single-component dir-relative operations.

    This is not a Linux runtime claim. It exercises the REAL extraction control
    flow, exclusive/no-follow flags, all short writes and final inode checks.
    """

    O_RDONLY, O_WRONLY = 0, 1
    O_DIRECTORY, O_NOFOLLOW, O_CREAT, O_EXCL, O_NONBLOCK = 2, 4, 8, 16, 32

    def __init__(self):
        self.nodes, self.fds, self.events = {}, {}, []
        self.add("/", stat.S_IFDIR | 0o755)
        self.add("/opt", stat.S_IFDIR | 0o755)

    def add(self, path, mode):
        self.nodes[path] = SimpleNamespace(
            st_dev=1,
            st_ino=len(self.nodes) + 1,
            st_mode=mode,
            st_uid=0,
            st_gid=0,
            st_nlink=1,
            data=bytearray(),
        )

    def resolve(self, name, dir_fd=None):
        if dir_fd is None:
            assert name == "/"
            return "/"
        assert name not in ("", ".", "..") and "/" not in name and "\\" not in name
        return str(PurePosixPath(self.fds[dir_fd][0]) / name)

    def open(self, name, flags, mode=0o777, *, dir_fd=None):
        assert flags & self.O_NOFOLLOW
        path = self.resolve(name, dir_fd)
        if flags & self.O_CREAT:
            assert flags & self.O_EXCL and dir_fd is not None
            if path in self.nodes:
                raise FileExistsError(path)
            self.add(path, stat.S_IFREG | mode)
            self.events.append(("create-file", path))
        node = self.nodes[path]
        if stat.S_ISLNK(node.st_mode):
            raise OSError("NOFOLLOW")
        if flags & self.O_DIRECTORY and not stat.S_ISDIR(node.st_mode):
            raise NotADirectoryError(path)
        fd = max(self.fds, default=9) + 1
        self.fds[fd] = path, node
        return fd

    def mkdir(self, name, mode, *, dir_fd):
        path = self.resolve(name, dir_fd)
        if path in self.nodes:
            raise FileExistsError(path)
        self.events.append(("mkdir", path))
        self.add(path, stat.S_IFDIR | mode)

    def fstat(self, fd):
        return self.fds[fd][1]

    def stat(self, name, *, dir_fd, follow_symlinks):
        assert follow_symlinks is False
        path = self.resolve(name, dir_fd)
        if path not in self.nodes:
            raise FileNotFoundError(path)
        return self.nodes[path]

    def fchown(self, fd, uid, gid):
        node = self.fstat(fd)
        node.st_uid, node.st_gid = uid, gid

    def fchmod(self, fd, mode):
        node = self.fstat(fd)
        node.st_mode = stat.S_IFMT(node.st_mode) | mode

    def fsync(self, fd):
        self.events.append(("fsync", self.fds[fd][0]))

    def close(self, fd):
        self.fds.pop(fd)

    def fdopen(self, fd, mode, buffering):
        owner = self

        class ShortWriter:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                owner.close(fd)

            def write(self, raw):
                count = min(len(raw), 3)
                owner.fstat(fd).data.extend(raw[:count])
                return count

        assert mode == "wb" and buffering == 0
        return ShortWriter()

    @contextmanager
    def _parent(self, path):
        assert str(path).replace("\\", "/") == deploy.TARGET
        with ExitStack() as stack:
            root = self.open("/", self.O_DIRECTORY | self.O_NOFOLLOW)
            stack.callback(self.close, root)
            parent = self.open("opt", self.O_DIRECTORY | self.O_NOFOLLOW, dir_fd=root)
            stack.callback(self.close, parent)
            chain = [(root, "opt", parent, deploy.metadata(self.fstat(parent)))]
            self._check(chain)
            yield stack, parent, PurePosixPath(deploy.TARGET).name, chain

    def _check(self, chain):
        for root, name, fd, before in chain:
            for opened in (root, fd):
                info = self.fstat(opened)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o7022:
                    raise ValueError("unsafe protected parent")
            if (
                deploy.metadata(self.stat(name, dir_fd=root, follow_symlinks=False)) != before
                or deploy.metadata(self.fstat(fd)) != before
            ):
                raise ValueError("Protected ancestor changed")


@pytest.mark.parametrize("kind", [stat.S_IFDIR, stat.S_IFREG, stat.S_IFLNK])
def test_exclusive_existing_target_refusal_without_writes(monkeypatch, kind):
    fs = FakeFDs()
    fs.add(deploy.TARGET, kind | 0o755)
    before = dict(fs.nodes)
    monkeypatch.setattr(deploy, "os", fs)
    with pytest.raises(FileExistsError):
        deploy.extract_new({"a": (b"data", 0o644)}, fs)
    assert fs.nodes == before
    assert fs.events == []
    assert fs.fds == {}


@pytest.mark.parametrize("origins_only", [False, True])
def test_host_composition_transport_is_fixed_and_evidence_exclusive(
    inputs, tmp_path, monkeypatch, origins_only
):
    raw, approval = inputs
    approval_raw = (json.dumps(approval, indent=2, sort_keys=True) + "\n").encode()
    assert hashlib.sha256(approval_raw).hexdigest() == deploy.APPROVAL_SHA
    guard = deploy.load_provider()
    receipt = dict(
        format=1,
        provider="fresh-wsl2-nspawn",
        distribution=guard.DISTRIBUTION,
        install_location=guard.LOCATION,
        machine=guard.MACHINE,
        nonce="1" * 64,
        outer_machine_id="2" * 32,
        inner_machine_id="3" * 32,
    )
    receipt_raw = json.dumps(receipt).encode()
    monkeypatch.setattr(deploy, "RECEIPT_SHA", hashlib.sha256(receipt_raw).hexdigest())
    archive_path, approval_path, receipt_path = [
        tmp_path / n for n in ("a.tar", "a.json", "r.json")
    ]
    archive_path.write_bytes(raw)
    approval_path.write_bytes(approval_raw)
    receipt_path.write_bytes(receipt_raw)
    out = tmp_path / "private-new-out"
    argv = [
        "deploy",
        "--archive",
        str(archive_path),
        "--approval",
        str(approval_path),
        "--approval-sha256",
        deploy.APPROVAL_SHA,
        "--operator-sha256",
        hashlib.sha256(Path(deploy.__file__).read_bytes()).hexdigest(),
        "--receipt",
        str(receipt_path),
        "--evidence-dir",
        str(out),
    ] + (["--origins-only"] if origins_only else [])
    monkeypatch.setattr(deploy.sys, "argv", argv)
    events = []
    guard.registration = lambda: events.append("registration") or [
        dict(
            DistributionName=guard.DISTRIBUTION,
            BasePath=guard.LOCATION,
            Version=2,
        )
    ]
    guard.preflight = lambda r: events.append("preflight") or {"observed": True}
    monkeypatch.setattr(deploy, "load_provider", lambda: guard)

    def transported(argv, **kwargs):
        events.append("transport")
        assert argv == [
            "wsl.exe",
            "-d",
            guard.DISTRIBUTION,
            "--",
            "/usr/bin/systemd-run",
            "--machine=" + guard.MACHINE,
            "--wait",
            "--pipe",
            "--collect",
            "/opt/knxoh-test-venv/bin/python",
            "-I",
            "-B",
            "-",
        ]
        program = kwargs["input"]
        compile(program, "<offline payload>", "exec")
        assert program.index("exec(compile(") < program.index("\nADOPTION_SOURCE=")
        assert program.startswith("__name__='_deployment_payload'\n")
        result = dict(
            head=deploy.HEAD,
            root=deploy.TARGET,
            archive_sha256=deploy.ARCHIVE_SHA,
            files=269,
            verified=True,
        )
        if origins_only:
            assert "\nresult=guest_origins(" in program
            result = dict(
                head=deploy.HEAD,
                root=deploy.TARGET,
                origins_verified=True,
                module_file=deploy.TARGET + "/tests/integration/test_update_systemd.py",
                callback_filename=deploy.TARGET + "/tests/integration/test_update_systemd.py",
                adapter_filename=deploy.TARGET + "/installer/update_core/systemd.py",
            )
        else:
            assert "\nresult=guest_deploy(" in program
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(deploy.subprocess, "run", transported)
    assert deploy.main() == 0
    assert events == ["registration", "preflight", "transport"]
    phase = "origins" if origins_only else "deployment"
    observed = (out / (phase + "-receipt.json")).read_text()
    assert receipt["nonce"] not in observed
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        deploy.main()
    assert events.count("transport") == 1
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}


@pytest.mark.parametrize("unsafe", ["owner", "group", "writable", "symlink"])
def test_unsafe_opt_precedes_mkdir(monkeypatch, unsafe):
    fs = FakeFDs()
    node = fs.nodes["/opt"]
    if unsafe == "owner":
        node.st_uid = 10
    elif unsafe == "group":
        node.st_gid = 10
    else:
        node.st_mode = (stat.S_IFLNK | 0o755) if unsafe == "symlink" else stat.S_IFDIR | 0o777
    monkeypatch.setattr(deploy, "os", fs)
    with pytest.raises((ValueError, OSError)):
        deploy.extract_new({"a": (b"data", 0o644)}, fs)
    assert fs.events == []
    assert fs.fds == {}


def test_fd_relative_extraction_normalizes_and_completes_short_writes(monkeypatch):
    fs = FakeFDs()
    monkeypatch.setattr(deploy, "os", fs)
    files = {"a/b/file": (b"0123456789", 0o644), "run": (b"#!/bin/sh\n", 0o755)}
    deploy.extract_new(files, fs)
    for name, (raw, mode) in files.items():
        node = fs.nodes[deploy.TARGET + "/" + name]
        assert bytes(node.data) == raw
        assert stat.S_IMODE(node.st_mode) == mode
        assert (node.st_uid, node.st_gid) == (0, 0)
    assert {p for event, p in fs.events if event == "fsync"} == set(fs.nodes) - {"/"}
    assert fs.fds == {}


def test_replaced_opt_name_detected_by_held_parent_fd(monkeypatch):
    fs = FakeFDs()
    original = fs.fsync

    def race(fd):
        original(fd)
        if fs.fds[fd][0] == "/opt":
            fs.nodes["/opt"] = SimpleNamespace(**vars(fs.nodes["/opt"]))
            fs.nodes["/opt"].st_ino += 1000

    fs.fsync = race
    monkeypatch.setattr(deploy, "os", fs)
    with pytest.raises(ValueError, match="ancestor changed"):
        deploy.extract_new({"a": (b"retained", 0o644)}, fs)
    assert deploy.TARGET in fs.nodes  # No rollback/removal of partial evidence.
    assert fs.fds == {}


def test_old_guard_pins_are_historical_git_blobs():
    for name, digest in deploy.OLD_FILES.items():
        raw = subprocess.check_output(["git", "show", "d1f1848:" + name])
        assert hashlib.sha256(raw).hexdigest() == digest


def test_json_duplicates_and_constants_rejected():
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
        with pytest.raises(ValueError):
            deploy.strict_json(raw)


@pytest.mark.parametrize("failure", ["old-guard", "inventory", "ambient", None])
def test_separate_origin_check_orders_authorization_inventory_and_import(monkeypatch, failure):
    events = []

    def authorize(argv, **kwargs):
        events.append("old-guard")
        assert argv[1:] == ["-I", "-B", "-"]
        assert "old_guard(" in kwargs["input"]
        assert "guest_deploy(" not in kwargs["input"]
        if failure == "old-guard":
            raise ValueError("original guard refused")

    def inventory(*args):
        events.append("inventory")
        if failure == "inventory":
            raise ValueError("inventory refused")
        return {
            "refuse_cached_modules": lambda m: events.append("fresh-cache"),
            "verify_origins": lambda *a: events.append("actual-origins"),
        }

    def forbidden_callback(*args):
        pytest.fail("must never invoke the callback")

    module = SimpleNamespace(
        __file__=deploy.TARGET + "/tests/integration/test_update_systemd.py",
        test_real_migration_child_no_live_state_sudo_or_surviving_writer=forbidden_callback,
        SystemdAdapter=SimpleNamespace(__init__=lambda: None),
    )

    def imported(name):
        assert name == "test_update_systemd"
        events.append("new-import")
        return module

    monkeypatch.setattr(deploy.subprocess, "run", authorize)
    monkeypatch.setattr(deploy, "verify_deployed", inventory)
    monkeypatch.setattr(deploy.importlib, "import_module", imported)

    def selected(name):
        if name == "scripts":
            return SimpleNamespace(
                submodule_search_locations=[
                    "/ambient/scripts" if failure == "ambient" else deploy.TARGET + "/scripts"
                ]
            )
        relative = (
            "installer/__init__.py"
            if name == "installer"
            else "tests/integration/test_update_systemd.py"
        )
        return SimpleNamespace(origin=deploy.TARGET + "/" + relative)

    monkeypatch.setattr(deploy.importlib.util, "find_spec", selected)
    monkeypatch.setattr(
        deploy, "sys", SimpleNamespace(executable="test-python", modules={}, path=[])
    )
    monkeypatch.setattr(deploy, "extract_new", lambda *a: pytest.fail("readonly write"))
    if failure:
        with pytest.raises(ValueError):
            deploy.guest_origins("# pinned operator", {}, {})
        assert "new-import" not in events
    else:
        assert deploy.guest_origins("# pinned operator", {}, {})["origins_verified"] is True
        assert events == ["old-guard", "inventory", "fresh-cache", "new-import", "actual-origins"]


@pytest.mark.parametrize(
    "failure", ["bytes", "cache", "namespace", "receipt", "live", "origin", None]
)
def test_real_old_guard_excludes_target_effects(monkeypatch, failure):
    old_sources = {
        name: subprocess.check_output(["git", "show", "d1f1848:" + name])
        for name in deploy.OLD_FILES
    }
    events = []
    receipt_raw = b'{"inner_machine_id":"inner","nonce":"offline"}'
    receipt = json.loads(receipt_raw)

    def read(path, *args):
        if path == "/etc/knxoh-nested-acceptance.json":
            return b"bad" if failure == "receipt" else receipt_raw
        value = old_sources[path.removeprefix(deploy.OLD + "/")]
        return b"bad" if failure == "bytes" else value

    fs = FakeFDs()
    fs.name, fs.geteuid = "posix", lambda: 0
    for path in (
        deploy.OLD,
        deploy.OLD + "/tests",
        deploy.OLD + "/tests/integration",
        deploy.OLD + "/scripts",
        deploy.OLD + "/installer",
        deploy.OLD + "/installer/update_core",
    ):
        fs.add(path, stat.S_IFDIR | 0o755)
    if failure == "cache":
        fs.add(deploy.OLD + "/tests/integration/__pycache__", stat.S_IFDIR | 0o755)
    if failure == "namespace":
        fs.add(deploy.OLD + "/scripts/__init__.pyc", stat.S_IFREG | 0o644)

    class FakePath:
        def __init__(self, path):
            self.path = path

        def lstat(self):
            if self.path not in fs.nodes:
                raise FileNotFoundError(self.path)
            return fs.nodes[self.path]

        def read_text(self):
            assert self.path == "/etc/machine-id"
            return receipt["inner_machine_id"]

    def live(*args):
        events.append("original-live-guard")
        if failure == "live":
            raise ValueError("live guard refused")

    def imported(name):
        assert name == "test_update_systemd"
        events.append("old-guard-import")
        deploy.sys.modules["installer.update_core.secure_fs"] = SimpleNamespace(
            __file__=("/ambient" if failure == "origin" else deploy.OLD)
            + "/installer/update_core/secure_fs.py"
        )
        return SimpleNamespace(_check_virtualization=live)

    monkeypatch.setattr(deploy, "os", fs)
    monkeypatch.setattr(deploy, "Path", FakePath)
    monkeypatch.setattr(deploy, "sys", SimpleNamespace(modules={}, path=[]))
    monkeypatch.setattr(deploy, "protected_read", read)
    monkeypatch.setattr(deploy, "RECEIPT_SHA", hashlib.sha256(receipt_raw).hexdigest())
    monkeypatch.setattr(deploy.importlib, "import_module", imported)
    monkeypatch.setattr(
        deploy.importlib.util,
        "find_spec",
        lambda *a: SimpleNamespace(
            submodule_search_locations=[deploy.OLD + "/scripts"],
            origin=deploy.OLD + "/tests/integration/test_update_systemd.py",
        ),
    )

    def selected(module, search):
        name = (
            "tests/integration/test_update_systemd.py"
            if module == "test_update_systemd"
            else module.replace(".", "/")
            + ("/__init__.py" if module in ("installer", "installer.update_core") else ".py")
        )
        path = deploy.OLD + "/" + name
        return SimpleNamespace(
            origin=path, loader=deploy.importlib.machinery.SourceFileLoader(module, path)
        )

    monkeypatch.setattr(deploy.importlib.machinery.PathFinder, "find_spec", selected)
    monkeypatch.setattr(deploy, "extract_new", lambda *a: pytest.fail("target write"))
    if failure:
        with pytest.raises(ValueError):
            deploy.old_guard(receipt)
    else:
        helper = deploy.old_guard(receipt)
        assert helper is deploy.sys.modules["installer.update_core.secure_fs"]
    if failure in ("bytes", "cache", "namespace"):
        assert events == []
    elif failure == "receipt":
        assert events == ["old-guard-import"]
    else:
        assert events == ["old-guard-import", "original-live-guard"]
    assert fs.events == []
    assert fs.fds == {}
