"""Real bounded archive operations; no network or privileged candidate execution."""

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from installer.update_core import artifacts
from installer.update_core.protocol import Limits


@pytest.fixture
def release():
    name = "knx_to_openhab-1.2.3.tar.gz"
    url = f"https://github.com/{artifacts.REPOSITORY}/releases/download/v1.2.3/{name}"
    return artifacts.ReleaseInfo("1.2.3", "v1.2.3", name, url, url + ".sha256")


def make_archive(path, entries):
    with tarfile.open(path, "w:gz") as archive:
        for name, payload, kind in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.mode = 0o644
            entry.size = len(payload) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                entry.linkname = "/etc/shadow"
            archive.addfile(entry, io.BytesIO(payload))


def contract():
    return json.dumps(
        dict(
            updater_protocol=1,
            config_copy_protocol=1,
            accepted_input_schema_versions=[0, 1],
            output_schema_version=1,
            runtime_backward_compatible=True,
        )
    ).encode()


def good_entries():
    prefix = "knx_to_openhab-1.2.3"
    return [(prefix, b"", tarfile.DIRTYPE)] + [
        (prefix + "/" + name, data, kind)
        for name, data, kind in [
            ("VERSION", b"1.2.3\n", tarfile.REGTYPE),
            ("installer/update_contract.json", contract(), tarfile.REGTYPE),
            ("requirements.txt", b"", tarfile.REGTYPE),
            ("installer/config_migrations.py", b"# candidate", tarfile.REGTYPE),
        ]
    ]


def test_checksum_strict_and_archive_corruption(tmp_path, release):
    archive = tmp_path / "archive"
    make_archive(archive, good_entries())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest().encode()
    artifacts.verify_archive_bytes(
        archive.read_bytes(), checksum + b"  " + release.archive_name.encode() + b"\n", release
    )
    for data in (
        b"",
        b"0" * 64,
        checksum + b"  other.tar.gz\n",
        checksum + b"  " + release.archive_name.encode() + b"\nextra",
    ):
        with pytest.raises(ValueError):
            artifacts.verify_archive_bytes(archive.read_bytes(), data, release)
    with pytest.raises(ValueError):
        artifacts.verify_archive_bytes(
            archive.read_bytes()[:-5], checksum + b"  " + release.archive_name.encode(), release
        )


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("a/../../escape", tarfile.REGTYPE),
        ("a\\escape", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hard", tarfile.LNKTYPE),
        ("fifo", tarfile.FIFOTYPE),
        ("device", tarfile.CHRTYPE),
        ("sparse", tarfile.GNUTYPE_SPARSE),
        ("VERSION", tarfile.REGTYPE),
    ],
)
def test_reject_unsafe_archive(tmp_path, release, name, kind):
    archive = tmp_path / "archive"
    member = name if name.startswith("/") else "knx_to_openhab-1.2.3/" + name
    make_archive(archive, good_entries() + [(member, b"x", kind)])
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "tree", release)
    assert not (tmp_path / "escape").exists()


def test_extract_validates_version_contract_and_expansion(tmp_path, release, monkeypatch):
    archive = tmp_path / "archive"
    make_archive(archive, good_entries())
    root = tmp_path / "tree"
    artifacts.extract_archive(archive, root, release)
    assert (root / "VERSION").read_bytes() == b"1.2.3\n"
    monkeypatch.setattr(Limits, "TREE_ENTRIES", 2)
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "limited", release)


@pytest.mark.parametrize("limit", ["ARCHIVE_BYTES", "TREE_BYTES", "FILE_BYTES"])
def test_archive_budgets(tmp_path, release, monkeypatch, limit):
    archive = tmp_path / "archive"
    make_archive(archive, good_entries())
    monkeypatch.setattr(Limits, limit, 2)
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "tree", release)


def test_truncated_gzip_and_wrong_layout(tmp_path, release):
    archive = tmp_path / "archive"
    make_archive(archive, good_entries())
    archive.write_bytes(archive.read_bytes()[:-5])
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "truncated", release)
    make_archive(archive, [("other/VERSION", b"1.2.3", tarfile.REGTYPE)])
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "layout", release)


@pytest.mark.parametrize("fault", ["setid", "group-write", "version", "contract"])
def test_reject_privilege_bits_and_invalid_release_data(tmp_path, release, fault):
    archive = tmp_path / "archive"
    entries = good_entries()
    if fault in ("version", "contract"):
        index = 1 if fault == "version" else 2
        name, _, kind = entries[index]
        entries[index] = (name, b"9.9.9" if fault == "version" else b"{}", kind)
    make_archive(archive, entries)
    if fault in ("setid", "group-write"):
        with tarfile.open(archive, "r:gz") as source:
            payloads = [
                (entry, source.extractfile(entry).read() if entry.isreg() else b"")
                for entry in source
            ]
        with tarfile.open(archive, "w:gz") as target:
            for entry, payload in payloads:
                entry.mode = 0o4644 if fault == "setid" else 0o664
                target.addfile(entry, io.BytesIO(payload))
    with pytest.raises(ValueError):
        artifacts.extract_archive(archive, tmp_path / "tree", release)


def test_fixed_resource_budgets():
    assert Limits.ARCHIVE_BYTES == 128 * 1024**2
    assert Limits.TREE_BYTES == 512 * 1024**2
    assert Limits.FILE_BYTES == 64 * 1024**2
    assert Limits.TREE_ENTRIES == 20_000
    assert Limits.DEPENDENCY_TIMEOUT_SECONDS == 900
    assert Limits.COORDINATOR_NOFILE == 32768


@pytest.mark.skipif(os.name != "posix", reason="POSIX bounded freeze")
@pytest.mark.parametrize("limit", ["TREE_ENTRIES", "TREE_BYTES", "FILE_BYTES", "TREE_DEPTH"])
def test_freeze_bounds_entire_dependency_tree_before_chown(monkeypatch, limit):
    import tempfile

    from installer.update_core import secure_fs

    if os.geteuid() != 0:
        pytest.skip("requires isolated root test process")
    with tempfile.TemporaryDirectory(dir="/root") as directory:
        root = Path(directory) / "candidate"
        (root / "venv/lib").mkdir(parents=True)
        (root / "venv/lib/dependency").write_bytes(b"large dependency")
        for path in [root, *root.rglob("*")]:
            os.chown(path, 12345, 12345)
        monkeypatch.setattr(Limits, limit, 1)
        with pytest.raises(ValueError):
            secure_fs.freeze_tree(root, 12345)
        assert root.stat().st_uid == 12345


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a",
        "https://evil.test/a",
        "https://github.com.evil/a",
        "https://user@github.com/a",
        "https://github.com:443/a",
        "https://github.com/a\n",
    ],
)
def test_redirect_host_validation(url):
    with pytest.raises(ValueError):
        artifacts.validate_download_url(url)


def test_all_approved_redirect_hosts():
    for host in (
        "api.github.com",
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    ):
        assert artifacts.validate_download_url(f"https://{host}/asset?token=x")


def test_redirect_hook_checks_before_following():
    import urllib.request

    from installer.update_prepare import SafeRedirect

    handler = SafeRedirect()
    request = urllib.request.Request("https://github.com/source")
    with pytest.raises(ValueError):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.test/target")


@pytest.mark.parametrize(
    "body,length,limit", [(b"abc", "5", 10), (b"abc", "3", 2), (b"abc", None, 2)]
)
def test_http_truncation_and_bounds(monkeypatch, body, length, limit):
    from installer import update_prepare

    class Response(io.BytesIO):
        headers = {} if length is None else {"Content-Length": length}

        def geturl(self):
            return "https://objects.githubusercontent.com/file"

    class Opener:
        def open(self, request, timeout):
            assert timeout == Limits.HTTP_TIMEOUT_SECONDS
            return Response(body)

    monkeypatch.setattr(update_prepare.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(ValueError):
        update_prepare.download("https://github.com/file", limit)


def test_extract_stage_uses_parent_verified_archive_only(monkeypatch, tmp_path, release):
    from dataclasses import asdict

    from installer import update_prepare

    monkeypatch.setattr(update_prepare.os, "geteuid", lambda: 12345, raising=False)
    (tmp_path / "input.json").write_text(json.dumps({"release": asdict(release)}))
    calls = []
    monkeypatch.setattr(update_prepare, "extract_archive", lambda *args: calls.append(args))
    update_prepare.run_stage("extract", tmp_path, tmp_path / "candidate")
    assert calls[0][0] == tmp_path / "verified.tar.gz"


@pytest.mark.skipif(os.name != "posix", reason="POSIX protected archive")
def test_parent_verify_archive_and_reject_child_owned_input(release):
    import tempfile

    if os.geteuid() != 0:
        pytest.skip("requires isolated root test process")
    with tempfile.TemporaryDirectory(dir="/root") as directory:
        path = Path(directory) / "verified.tar.gz"
        make_archive(path, good_entries())
        checksum = (
            hashlib.sha256(path.read_bytes()).hexdigest().encode()
            + b"  "
            + release.archive_name.encode()
        )
        artifacts.verify_archive(path, checksum, release)
        os.chown(path, 12345, 12345)
        with pytest.raises(ValueError):
            artifacts.verify_archive(path, checksum, release)


@pytest.mark.skipif(os.name != "posix", reason="POSIX root-private ingestion")
def test_stopped_output_ingestion_and_tree_validation(release):
    import tempfile

    if os.geteuid() != 0:
        pytest.skip("requires isolated root test process")
    with tempfile.TemporaryDirectory(dir="/root") as temporary:
        parent = Path(temporary)
        output = parent / "output"
        output.mkdir(mode=0o700)
        file = output / "metadata.json"
        file.write_bytes(b"{}")
        os.chown(file, 12345, 12345)
        os.chown(output, 12345, 12345)
        with pytest.raises(ValueError, match="stopped"):
            artifacts.ingest_child_file(output, "metadata.json", 2, 12345, stopped=False)
        assert artifacts.ingest_child_file(output, "metadata.json", 2, 12345, stopped=True) == b"{}"
        with pytest.raises(ValueError):
            artifacts.ingest_child_file(output, "metadata.json", 1, 12345, stopped=True)
        file.unlink()
        file.symlink_to("/etc/passwd")
        with pytest.raises((ValueError, OSError)):
            artifacts.ingest_child_file(output, "metadata.json", 1024, 12345, stopped=True)
        root = parent / "candidate"
        archive = parent / "archive"
        make_archive(archive, good_entries())
        artifacts.extract_archive(archive, root, release)
        assert artifacts.validate_extracted_tree(root, release).updater_protocol == 1
        for entry in [root, *root.rglob("*")]:
            os.chown(entry, 12345, 12345)
        with pytest.raises(ValueError):
            artifacts.validate_extracted_tree(root, release)
        assert (
            artifacts.validate_extracted_tree(root, release, expected_uid=12345).updater_protocol
            == 1
        )
        (root / "VERSION").write_text("9.9.9")
        with pytest.raises(ValueError):
            artifacts.validate_extracted_tree(root, release, expected_uid=12345)
