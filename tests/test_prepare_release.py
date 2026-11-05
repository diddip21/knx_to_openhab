import hashlib
import io
import json
import shutil
import tarfile
from pathlib import PurePosixPath

import pytest

import installer.prepare_release as prepare_release_module
from installer.prepare_release import (
    ReleasePreparationError,
    prepare_release,
    verify_and_extract,
)
from scripts.build_release import build_release

_VERSION = "1.2.3"
_TAG = f"v{_VERSION}"
_ROOT = f"knx_to_openhab-{_VERSION}"
_COMMIT = "a" * 40
_REQUIRED_FILES = {
    "requirements.txt": b"flask==3.0.0\n",
    "update.sh": b"#!/bin/bash\n",
    "knxoh_paths.py": b"# path helper\n",
    "installer/create_update_backup.py": b"# backup helper\n",
    "installer/prepare_release.py": b"# release helper\n",
    "installer/launch_web.sh": b"#!/bin/bash\n",
    "web_ui/backend/app.py": b"# application\n",
}


def _make_archive(tmp_path, extra_members=(), *, version=_VERSION):
    root_name = f"knx_to_openhab-{version}"
    archive_path = tmp_path / f"{root_name}.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for relative, content in _REQUIRED_FILES.items():
            member = tarfile.TarInfo(f"{root_name}/{relative}")
            member.size = len(content)
            member.mode = 0o755 if relative.endswith(".sh") else 0o644
            archive.addfile(member, io.BytesIO(content))
        for member, content in extra_members:
            if content is None:
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    checksum_path = tmp_path / f"{archive_path.name}.sha256"
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    return archive_path, checksum_path


def _verify(archive_path, checksum_path, destination, *, tag=_TAG):
    return verify_and_extract(
        archive_path,
        checksum_path,
        destination,
        repository="diddip21/knx_to_openhab",
        tag=tag,
        commit_hash=_COMMIT,
        commit_date="2026-11-03T00:00:00Z",
        commit_message="Stable release",
        author="Release Bot",
    )


def _make_commit_source(tmp_path, *, app_content=None, unsafe_member=None):
    source_root = tmp_path / "source" / f"knx_to_openhab-{_COMMIT[:12]}"
    source_root.mkdir(parents=True)
    files = {"VERSION": f"{_VERSION}\n".encode(), **_REQUIRED_FILES}
    if app_content is not None:
        files["web_ui/backend/app.py"] = app_content

    manifest = []
    for relative, content in files.items():
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        mode = 0o100755 if relative.endswith(".sh") else 0o100644
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        manifest.append((PurePosixPath(relative), mode, blob))

    source_archive = tmp_path / "source.tar.gz"
    with tarfile.open(source_archive, "w:gz") as archive:
        root = tarfile.TarInfo(source_root.name)
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for relative, content in files.items():
            member = tarfile.TarInfo(f"{source_root.name}/{relative}")
            member.size = len(content)
            member.mode = 0o755 if relative.endswith(".sh") else 0o644
            archive.addfile(member, io.BytesIO(content))
        if unsafe_member is not None:
            member = tarfile.TarInfo(unsafe_member)
            content = b"outside"
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return source_root, manifest, source_archive


def _make_commit_release_asset(tmp_path, *, app_content=None):
    source_root, manifest, source_archive = _make_commit_source(tmp_path, app_content=app_content)
    archive_path, checksum_path = build_release(
        source_root,
        _VERSION,
        tmp_path / "release-assets",
        tracked_files=[(path, mode) for path, mode, _blob in manifest],
    )
    return archive_path, checksum_path, manifest, source_archive


def _mock_prepare_downloads(monkeypatch, archive_path, checksum_path, source_archive, manifest):
    requested_urls = []

    def fake_download(url, destination, *, limit=256 * 1024 * 1024):
        requested_urls.append(url)
        if url.endswith(".sha256"):
            source = checksum_path
        elif "/tarball/" in url:
            source = source_archive
        else:
            source = archive_path
        shutil.copyfile(source, destination)

    monkeypatch.setattr(prepare_release_module, "_download", fake_download)
    monkeypatch.setattr(
        prepare_release_module,
        "_fetch_commit_file_manifest",
        lambda _repository, _commit: manifest,
        raising=False,
    )
    return requested_urls


def test_verifies_checksum_extracts_release_and_writes_metadata(tmp_path):
    archive_path, checksum_path = _make_archive(tmp_path)
    destination = tmp_path / "stage"

    release_dir = _verify(archive_path, checksum_path, destination)

    metadata = json.loads((release_dir / "version.json").read_text(encoding="utf-8"))
    assert release_dir == destination / _ROOT
    assert metadata["release_tag"] == _TAG
    assert metadata["commit_hash"] == _COMMIT
    assert metadata["commit_short"] == _COMMIT[:7]
    assert (release_dir / "requirements.txt").read_bytes() == _REQUIRED_FILES["requirements.txt"]
    assert (release_dir / "update.sh").stat().st_mode & 0o111


def test_rejects_a_checksum_mismatch_without_leaving_extracted_files(tmp_path):
    archive_path, checksum_path = _make_archive(tmp_path)
    checksum_path.write_text(f"{'0' * 64}  {archive_path.name}\n", encoding="ascii")
    destination = tmp_path / "stage"

    with pytest.raises(ReleasePreparationError, match="SHA-256"):
        _verify(archive_path, checksum_path, destination)

    assert list(destination.iterdir()) == []


@pytest.mark.parametrize(
    "name",
    [
        f"{_ROOT}/../outside.txt",
        "/absolute.txt",
        f"{_ROOT}/nested\\outside.txt",
    ],
)
def test_rejects_unsafe_archive_paths(tmp_path, name):
    extra = tarfile.TarInfo(name)
    extra.size = 4
    archive_path, checksum_path = _make_archive(tmp_path, [(extra, b"nope")])
    destination = tmp_path / "stage"

    with pytest.raises(ReleasePreparationError, match="Unsafe release archive path"):
        _verify(archive_path, checksum_path, destination)

    assert not (tmp_path / "outside.txt").exists()


def test_rejects_symbolic_links_in_release_archives(tmp_path):
    link = tarfile.TarInfo(f"{_ROOT}/web_ui/backend/leak")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../outside"
    archive_path, checksum_path = _make_archive(tmp_path, [(link, None)])
    destination = tmp_path / "stage"

    with pytest.raises(ReleasePreparationError, match="Unsupported release archive entry"):
        _verify(archive_path, checksum_path, destination)


def test_rejects_prerelease_and_nonempty_staging_directory(tmp_path):
    archive_path, checksum_path = _make_archive(tmp_path)
    with pytest.raises(ReleasePreparationError, match="stable SemVer"):
        _verify(archive_path, checksum_path, tmp_path / "stage", tag="v1.2.3-rc.1")

    destination = tmp_path / "nonempty"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ReleasePreparationError, match="must be empty"):
        _verify(archive_path, checksum_path, destination)
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_prepare_release_downloads_expected_https_assets_and_cleans_staging(monkeypatch, tmp_path):
    archive_path, checksum_path = _make_archive(tmp_path, version="1.2.3+build.1")
    requested_urls = []
    monkeypatch.setattr(
        "installer.prepare_release._verify_release_matches_commit",
        lambda *_args, **_kwargs: None,
    )

    def fake_download(url, destination, *, limit=256 * 1024 * 1024):
        requested_urls.append(url)
        source = checksum_path if url.endswith(".sha256") else archive_path
        destination.write_bytes(source.read_bytes())

    monkeypatch.setattr("installer.prepare_release._download", fake_download)
    destination = tmp_path / "stage"

    release_dir = prepare_release(
        destination,
        repository="diddip21/knx_to_openhab",
        tag="v1.2.3+build.1",
        commit_hash=_COMMIT,
        commit_date="2026-11-03T00:00:00Z",
        commit_message="Stable release",
        author="Release Bot",
    )

    assert release_dir.name == "knx_to_openhab-1.2.3+build.1"
    assert len(requested_urls) == 2
    assert all(
        url.startswith("https://github.com/diddip21/knx_to_openhab/releases/download/")
        for url in requested_urls
    )
    assert "%2B" in requested_urls[0]
    assert not list(tmp_path.glob(".assets-*"))


def test_prepare_release_accepts_archive_rebuilt_from_selected_commit(monkeypatch, tmp_path):
    archive_path, checksum_path, manifest, source_archive = _make_commit_release_asset(tmp_path)
    requested_urls = _mock_prepare_downloads(
        monkeypatch, archive_path, checksum_path, source_archive, manifest
    )
    destination = tmp_path / "stage"

    release_dir = prepare_release(
        destination,
        repository="diddip21/knx_to_openhab",
        tag=_TAG,
        commit_hash=_COMMIT,
        commit_date="2026-11-03T00:00:00Z",
        commit_message="Stable release",
        author="Release Bot",
    )

    assert release_dir == destination / _ROOT
    assert (release_dir / "web_ui/backend/app.py").read_bytes() == _REQUIRED_FILES[
        "web_ui/backend/app.py"
    ]
    assert any("/tarball/" in url for url in requested_urls)
    assert not list(tmp_path.glob(".assets-*"))


def test_prepare_release_rejects_asset_replacement_even_with_matching_checksum(
    monkeypatch, tmp_path
):
    commit_archive, _commit_checksum, manifest, source_archive = _make_commit_release_asset(
        tmp_path / "selected-commit"
    )
    substituted_archive, substituted_checksum, _other_manifest, _other_source = (
        _make_commit_release_asset(
            tmp_path / "substituted-release",
            app_content=b"malicious substituted application\n",
        )
    )
    assert substituted_archive != commit_archive
    assert substituted_checksum.read_text(encoding="ascii").startswith(
        hashlib.sha256(substituted_archive.read_bytes()).hexdigest()
    )
    _mock_prepare_downloads(
        monkeypatch,
        substituted_archive,
        substituted_checksum,
        source_archive,
        manifest,
    )
    destination = tmp_path / "stage"

    with pytest.raises(ReleasePreparationError, match="selected commit"):
        prepare_release(
            destination,
            repository="diddip21/knx_to_openhab",
            tag=_TAG,
            commit_hash=_COMMIT,
            commit_date="2026-11-03T00:00:00Z",
            commit_message="Stable release",
            author="Release Bot",
        )

    assert list(destination.iterdir()) == []
    assert not list(tmp_path.glob(".assets-*"))


def test_prepare_release_rejects_truncated_commit_tree(monkeypatch, tmp_path):
    archive_path, checksum_path, manifest, source_archive = _make_commit_release_asset(tmp_path)
    _mock_prepare_downloads(monkeypatch, archive_path, checksum_path, source_archive, manifest)

    def truncated_manifest(_repository, _commit):
        raise ReleasePreparationError("Selected commit tree is truncated")

    monkeypatch.setattr(
        prepare_release_module,
        "_fetch_commit_file_manifest",
        truncated_manifest,
        raising=False,
    )

    with pytest.raises(ReleasePreparationError, match="truncated"):
        prepare_release(
            tmp_path / "stage",
            repository="diddip21/knx_to_openhab",
            tag=_TAG,
            commit_hash=_COMMIT,
            commit_date="2026-11-03T00:00:00Z",
            commit_message="Stable release",
            author="Release Bot",
        )

    assert not list(tmp_path.glob(".assets-*"))


def test_prepare_release_rejects_unsafe_commit_source_paths(monkeypatch, tmp_path):
    source_root, manifest, source_archive = _make_commit_source(
        tmp_path, unsafe_member="../outside.txt"
    )
    archive_path, checksum_path = build_release(
        source_root,
        _VERSION,
        tmp_path / "release-assets",
        tracked_files=[(path, mode) for path, mode, _blob in manifest],
    )
    _mock_prepare_downloads(monkeypatch, archive_path, checksum_path, source_archive, manifest)

    with pytest.raises(ReleasePreparationError, match="Unsafe.*source|source.*path"):
        prepare_release(
            tmp_path / "stage",
            repository="diddip21/knx_to_openhab",
            tag=_TAG,
            commit_hash=_COMMIT,
            commit_date="2026-11-03T00:00:00Z",
            commit_message="Stable release",
            author="Release Bot",
        )

    assert not (tmp_path / "outside.txt").exists()
    assert not list(tmp_path.glob(".assets-*"))


def test_prepare_release_rejects_untrusted_source_redirect(monkeypatch, tmp_path):
    class RedirectedResponse(io.BytesIO):
        headers = {}

        def geturl(self):
            return "https://attacker.example/source.tar.gz"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        prepare_release_module,
        "urlopen",
        lambda _request, timeout: RedirectedResponse(b"not trusted"),
    )

    with pytest.raises(ReleasePreparationError, match="untrusted host"):
        prepare_release_module._download(
            "https://api.github.com/repos/diddip21/knx_to_openhab/tarball/" + _COMMIT,
            tmp_path / "source.tar.gz",
        )


def test_download_accepts_github_source_snapshot_redirect(monkeypatch, tmp_path):
    class RedirectedResponse(io.BytesIO):
        headers = {"Content-Length": "7"}

        def geturl(self):
            return "https://codeload.github.com/diddip21/knx_to_openhab/tar.gz/" + _COMMIT

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(
        prepare_release_module,
        "urlopen",
        lambda _request, timeout: RedirectedResponse(b"snapshot"),
    )
    destination = tmp_path / "source.tar.gz"

    prepare_release_module._download(
        "https://api.github.com/repos/diddip21/knx_to_openhab/tarball/" + _COMMIT,
        destination,
    )

    assert destination.read_bytes() == b"snapshot"


def test_fetch_commit_file_manifest_rejects_truncated_tree(monkeypatch):
    class ApiResponse(io.BytesIO):
        headers = {}

        def __init__(self, body, url):
            super().__init__(body)
            self._url = url

        def geturl(self):
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout):
        url = request.full_url
        if "/git/commits/" in url:
            body = json.dumps({"tree": {"sha": "b" * 40}}).encode()
        else:
            body = json.dumps({"truncated": True, "tree": []}).encode()
        return ApiResponse(body, url)

    monkeypatch.setattr(prepare_release_module, "urlopen", fake_urlopen)

    with pytest.raises(ReleasePreparationError, match="truncated"):
        prepare_release_module._fetch_commit_file_manifest("diddip21/knx_to_openhab", _COMMIT)
