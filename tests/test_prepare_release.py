import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath

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


def _make_commit_source(
    tmp_path,
    *,
    app_content=None,
    unsafe_member=None,
    builder_source=None,
    extra_files=None,
):
    source_root = tmp_path / "source" / f"knx_to_openhab-{_COMMIT[:12]}"
    source_root.mkdir(parents=True)
    if builder_source is None:
        builder_source = (
            Path(__file__).resolve().parents[1] / "scripts/build_release.py"
        ).read_bytes()
    files = {
        "VERSION": f"{_VERSION}\n".encode(),
        **_REQUIRED_FILES,
        "scripts/build_release.py": builder_source,
        **(extra_files or {}),
    }
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


def test_safe_extract_does_not_cache_every_tar_member(monkeypatch, tmp_path):
    extra_members = []
    for index in range(128):
        member = tarfile.TarInfo(f"{_ROOT}/many/{index}.txt")
        extra_members.append((member, b""))
    archive_path, _checksum_path = _make_archive(tmp_path, extra_members)
    cached_member_counts = []
    original_next = tarfile.TarFile.next

    def track_member_cache(archive):
        member = original_next(archive)
        cached_member_counts.append(len(archive.members))
        return member

    monkeypatch.setattr(tarfile.TarFile, "next", track_member_cache)
    app_dir = tmp_path / "app"

    prepare_release_module._safe_extract(archive_path, app_dir, _ROOT)

    assert max(cached_member_counts) <= 1
    assert (app_dir / "many" / "127.txt").is_file()


def test_source_archive_preflight_does_not_cache_every_tar_member(monkeypatch, tmp_path):
    source_archive, _checksum_path = _make_archive(tmp_path)
    cached_member_counts = []
    original_next = tarfile.TarFile.next

    def track_member_cache(archive):
        member = original_next(archive)
        cached_member_counts.append(len(archive.members))
        return member

    monkeypatch.setattr(tarfile.TarFile, "next", track_member_cache)

    prepare_release_module._preflight_source_archive(source_archive)

    assert max(cached_member_counts) <= 1


def test_safe_extract_commit_source_does_not_cache_every_tar_member(monkeypatch, tmp_path):
    archive_path = tmp_path / "source.tar.gz"
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for index in range(32):
            payload = str(index).encode()
            member = tarfile.TarInfo(f"{root_name}/{index}.txt")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    monkeypatch.setattr(prepare_release_module, "_preflight_source_archive", lambda _path: None)
    cached_member_counts = []
    original_next = tarfile.TarFile.next

    def track_member_cache(archive):
        member = original_next(archive)
        cached_member_counts.append(len(archive.members))
        return member

    monkeypatch.setattr(tarfile.TarFile, "next", track_member_cache)

    extracted_root = prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert max(cached_member_counts) <= 1
    assert (extracted_root / "31.txt").read_bytes() == b"31"


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


def test_rejects_nul_byte_in_release_archive_path(tmp_path):
    member = tarfile.TarInfo(f"{_ROOT}/safe.txt")
    member.pax_headers = {"path": f"{_ROOT}/bad\0name"}
    archive_path, checksum_path = _make_archive(tmp_path, [(member, b"x")])
    destination = tmp_path / "stage"

    with pytest.raises(ReleasePreparationError, match="Unsafe release archive path"):
        _verify(archive_path, checksum_path, destination)

    assert list(destination.iterdir()) == []


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
    original_verify_and_extract = prepare_release_module.verify_and_extract

    def verify_after_scratch_cleanup(archive, checksum, destination, **metadata):
        assert archive.exists()
        assert checksum.exists()
        assert not (archive.parent / "source").exists()
        assert not (archive.parent / "rebuilt").exists()
        return original_verify_and_extract(archive, checksum, destination, **metadata)

    monkeypatch.setattr(prepare_release_module, "verify_and_extract", verify_after_scratch_cleanup)
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


def test_prepare_release_accepts_archive_recompressed_with_different_gzip_level(
    monkeypatch, tmp_path
):
    archive_path, checksum_path, manifest, source_archive = _make_commit_release_asset(tmp_path)
    original_archive = archive_path.read_bytes()
    recompressed_archive = gzip.compress(
        gzip.decompress(original_archive), compresslevel=1, mtime=0
    )
    assert recompressed_archive != original_archive
    archive_path.write_bytes(recompressed_archive)
    checksum_path.write_text(
        f"{hashlib.sha256(recompressed_archive).hexdigest()}  {archive_path.name}\n",
        encoding="ascii",
    )
    _mock_prepare_downloads(monkeypatch, archive_path, checksum_path, source_archive, manifest)

    release_dir = prepare_release(
        tmp_path / "stage",
        repository="diddip21/knx_to_openhab",
        tag=_TAG,
        commit_hash=_COMMIT,
        commit_date="2026-11-03T00:00:00Z",
        commit_message="Stable release",
        author="Release Bot",
    )

    assert release_dir == tmp_path / "stage" / _ROOT


def test_commit_source_archive_is_removed_before_rebuilding(monkeypatch, tmp_path):
    archive_path = tmp_path / "published.tar.gz"
    archive_path.write_bytes(b"published archive")
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    source_archive = scratch_dir / "commit-source.tar.gz"
    source_root = scratch_dir / "source" / "root"
    source_root.mkdir(parents=True)
    manifest = [(PurePosixPath("source.py"), 0o100644, "a" * 40)]
    monkeypatch.setattr(
        prepare_release_module,
        "_fetch_commit_file_manifest",
        lambda _repository, _commit_hash: manifest,
    )

    def fake_download(_url, destination):
        destination.write_bytes(b"downloaded source archive")

    monkeypatch.setattr(prepare_release_module, "_download", fake_download)
    monkeypatch.setattr(
        prepare_release_module,
        "_safe_extract_commit_source",
        lambda _source_archive, _scratch_dir: source_root,
    )
    monkeypatch.setattr(prepare_release_module, "_verify_commit_source_files", lambda *_args: None)

    class SelectedBuilder:
        @staticmethod
        def is_excluded_release_path(_relative_path):
            return False

        @staticmethod
        def build_release(_source_root, _version, output_dir, *, tracked_files):
            assert tracked_files == [(PurePosixPath("source.py"), 0o100644)]
            assert not source_archive.exists()
            output_dir.mkdir()
            rebuilt_archive = output_dir / "rebuilt.tar.gz"
            rebuilt_archive.write_bytes(b"rebuilt archive")
            return rebuilt_archive, output_dir / "rebuilt.tar.gz.sha256"

    monkeypatch.setattr(
        prepare_release_module,
        "_load_selected_release_builder",
        lambda *_args: SelectedBuilder,
    )
    monkeypatch.setattr(
        prepare_release_module,
        "_decompressed_archive_digest",
        lambda _path: "same-archive-digest",
    )

    prepare_release_module._verify_release_matches_commit(
        archive_path,
        repository="diddip21/knx_to_openhab",
        commit_hash=_COMMIT,
        version=_VERSION,
        scratch_dir=scratch_dir,
    )

    assert not source_archive.exists()


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


def test_prepare_release_uses_selected_commit_builder_after_packaging_rule_change(
    monkeypatch, tmp_path
):
    excluded_name = "selected-builder-excluded.txt"
    builder_source = (Path(__file__).resolve().parents[1] / "scripts/build_release.py").read_bytes()
    changed_builder_source = builder_source.replace(
        b"EXCLUDED_NAMES = {\n",
        f'EXCLUDED_NAMES = {{\n    "{excluded_name}",\n'.encode(),
        1,
    )
    assert changed_builder_source != builder_source
    source_root, manifest, source_archive = _make_commit_source(
        tmp_path,
        builder_source=changed_builder_source,
        extra_files={excluded_name: b"excluded by the selected builder\n"},
    )
    archive_path, checksum_path = build_release(
        source_root,
        _VERSION,
        tmp_path / "release-assets",
        tracked_files=[
            (path, mode) for path, mode, _blob in manifest if path != PurePosixPath(excluded_name)
        ],
    )
    _mock_prepare_downloads(monkeypatch, archive_path, checksum_path, source_archive, manifest)

    release_dir = prepare_release(
        tmp_path / "stage",
        repository="diddip21/knx_to_openhab",
        tag=_TAG,
        commit_hash=_COMMIT,
        commit_date="2026-11-03T00:00:00Z",
        commit_message="Release with updated packaging rules",
        author="Release Bot",
    )

    assert release_dir == tmp_path / "stage" / _ROOT
    assert not (release_dir / excluded_name).exists()


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
        "_open_url",
        lambda _request, **_kwargs: RedirectedResponse(b"not trusted"),
    )

    with pytest.raises(ReleasePreparationError, match="untrusted host"):
        prepare_release_module._download(
            "https://api.github.com/repos/diddip21/knx_to_openhab/tarball/" + _COMMIT,
            tmp_path / "source.tar.gz",
        )


def test_redirect_handler_rejects_untrusted_intermediate_host_before_following():
    handler_type = getattr(prepare_release_module, "_AllowlistedRedirectHandler", None)
    assert handler_type is not None, "redirect targets must be validated before urllib follows them"
    handler = handler_type({"api.github.com", "codeload.github.com"})
    request = prepare_release_module.Request("https://api.github.com/start")

    with pytest.raises(ReleasePreparationError, match="untrusted host"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {"Location": "https://attacker.example/then-allowed"},
            "https://attacker.example/then-allowed",
        )


def test_redirect_handler_rejects_https_downgrade_before_following():
    handler_type = getattr(prepare_release_module, "_AllowlistedRedirectHandler", None)
    assert handler_type is not None, "redirect targets must be validated before urllib follows them"
    handler = handler_type({"api.github.com"})
    request = prepare_release_module.Request("https://api.github.com/start")

    with pytest.raises(ReleasePreparationError, match="HTTPS"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {"Location": "http://api.github.com/downgrade"},
            "http://api.github.com/downgrade",
        )


def test_redirect_handler_allows_trusted_github_asset_host():
    handler = prepare_release_module._AllowlistedRedirectHandler(
        {"api.github.com", "codeload.github.com"}
    )
    request = prepare_release_module.Request("https://api.github.com/start")

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {"Location": "https://codeload.github.com/archive.tar.gz"},
        "https://codeload.github.com/archive.tar.gz",
    )

    assert redirected is not None
    assert redirected.full_url == "https://codeload.github.com/archive.tar.gz"


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
        "_open_url",
        lambda _request, **_kwargs: RedirectedResponse(b"snapshot"),
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

    def fake_open_url(request, *, timeout, allowed_hosts):
        url = request.full_url
        if "/git/commits/" in url:
            body = json.dumps({"tree": {"sha": "b" * 40}}).encode()
        else:
            body = json.dumps({"truncated": True, "tree": []}).encode()
        return ApiResponse(body, url)

    monkeypatch.setattr(prepare_release_module, "_open_url", fake_open_url)

    with pytest.raises(ReleasePreparationError, match="truncated"):
        prepare_release_module._fetch_commit_file_manifest("diddip21/knx_to_openhab", _COMMIT)


def test_fetch_commit_file_manifest_preserves_nonregular_entries(monkeypatch):
    version_content = f"{_VERSION}\n".encode()
    version_blob = hashlib.sha1(
        f"blob {len(version_content)}\0".encode() + version_content
    ).hexdigest()

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

    def fake_open_url(request, *, timeout, allowed_hosts):
        url = request.full_url
        if "/git/commits/" in url:
            body = json.dumps({"tree": {"sha": "b" * 40}}).encode()
        else:
            body = json.dumps(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "VERSION",
                            "mode": "100644",
                            "type": "blob",
                            "sha": version_blob,
                        },
                        {
                            "path": "tests/excluded-link",
                            "mode": "120000",
                            "type": "blob",
                            "sha": "c" * 40,
                        },
                        {
                            "path": "tests/excluded-submodule",
                            "mode": "160000",
                            "type": "commit",
                            "sha": "d" * 40,
                        },
                    ],
                }
            ).encode()
        return ApiResponse(body, url)

    monkeypatch.setattr(prepare_release_module, "_open_url", fake_open_url)

    manifest = prepare_release_module._fetch_commit_file_manifest(
        "diddip21/knx_to_openhab", _COMMIT
    )

    assert manifest == [
        (PurePosixPath("VERSION"), 0o100644, version_blob),
        (PurePosixPath("tests/excluded-link"), 0o120000, "c" * 40),
        (PurePosixPath("tests/excluded-submodule"), 0o160000, "d" * 40),
    ]


def test_safe_extract_commit_source_ignores_symlinks_at_excluded_paths(tmp_path):
    source_archive = tmp_path / "source.tar.gz"
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(source_archive, "w:gz") as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        content = f"{_VERSION}\n".encode()
        version = tarfile.TarInfo(f"{root_name}/VERSION")
        version.size = len(content)
        archive.addfile(version, io.BytesIO(content))
        excluded_link = tarfile.TarInfo(f"{root_name}/tests/excluded-link")
        excluded_link.type = tarfile.SYMTYPE
        excluded_link.linkname = "../../outside"
        archive.addfile(excluded_link)

    extracted_root = prepare_release_module._safe_extract_commit_source(source_archive, tmp_path)

    assert (extracted_root / "VERSION").read_bytes() == content
    assert not (extracted_root / "tests" / "excluded-link").exists()
    assert not (tmp_path / "outside").exists()


def test_safe_extract_commit_source_counts_excluded_files_toward_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", 10)
    source_archive = tmp_path / "source.tar.gz"
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(source_archive, "w:gz") as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for relative_path, content in (
            ("VERSION", b"1.2.3\n"),
            ("tests/excluded.txt", b"12345"),
        ):
            member = tarfile.TarInfo(f"{root_name}/{relative_path}")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

    with pytest.raises(ReleasePreparationError, match="Expanded commit source exceeds"):
        prepare_release_module._safe_extract_commit_source(source_archive, tmp_path)


def test_safe_extract_commit_source_counts_pax_metadata_toward_size_limit(monkeypatch, tmp_path):
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    baseline_archive = tmp_path / "baseline.tar.gz"
    pax_archive = tmp_path / "pax.tar.gz"

    for archive_path, pax_headers in (
        (baseline_archive, {}),
        (pax_archive, {"comment": "x" * 100_000}),
    ):
        with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            root = tarfile.TarInfo(root_name)
            root.type = tarfile.DIRTYPE
            root.pax_headers = pax_headers
            archive.addfile(root)

    baseline_size = len(gzip.decompress(baseline_archive.read_bytes()))
    pax_size = len(gzip.decompress(pax_archive.read_bytes()))
    assert pax_size > baseline_size

    exact_limit_scratch = tmp_path / "exact-limit"
    exact_limit_scratch.mkdir()
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", pax_size)
    extracted_root = prepare_release_module._safe_extract_commit_source(
        pax_archive, exact_limit_scratch
    )
    assert extracted_root.is_dir()

    below_limit_scratch = tmp_path / "below-limit"
    below_limit_scratch.mkdir()
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", baseline_size)
    with pytest.raises(ReleasePreparationError, match="Expanded commit source exceeds"):
        prepare_release_module._safe_extract_commit_source(pax_archive, below_limit_scratch)
    shutil.rmtree(below_limit_scratch)


def test_safe_extract_commit_source_rejects_truncated_gzip(tmp_path):
    source_archive, _ = _make_archive(tmp_path)
    truncated_archive = tmp_path / "truncated.tar.gz"
    truncated_archive.write_bytes(source_archive.read_bytes()[:-8])

    with pytest.raises(ReleasePreparationError, match="Could not extract commit source archive"):
        prepare_release_module._safe_extract_commit_source(truncated_archive, tmp_path)


def test_safe_extract_commit_source_streams_without_decompressed_temp(monkeypatch, tmp_path):
    source_archive, _ = _make_archive(tmp_path)

    def reject_decompressed_temp(*args, **kwargs):
        pytest.fail("source extraction must not stage a decompressed temporary tar")

    monkeypatch.setattr(prepare_release_module.tempfile, "TemporaryFile", reject_decompressed_temp)

    extracted_root = prepare_release_module._safe_extract_commit_source(source_archive, tmp_path)

    assert extracted_root.is_dir()
    assert (extracted_root / "requirements.txt").read_bytes() == b"flask==3.0.0\n"


@pytest.mark.parametrize(
    ("pax_headers", "payload"),
    [
        ({"GNU.sparse.size": "1"}, b"X"),
        ({"GNU.sparse.map": "0,1", "GNU.sparse.size": "1"}, b"X"),
        (
            {
                "GNU.sparse.major": "1",
                "GNU.sparse.minor": "0",
                "GNU.sparse.realsize": "1",
            },
            b"1\n0\n1\nX",
        ),
    ],
    ids=("pax-sparse-0.0", "pax-sparse-0.1", "pax-sparse-1.0"),
)
def test_safe_extract_commit_source_rejects_sparse_members(tmp_path, pax_headers, payload):
    archive_path = tmp_path / "sparse.tar.gz"
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(f"{root_name}/sparse.bin")
        member.size = len(payload)
        member.pax_headers = pax_headers
        archive.addfile(member, io.BytesIO(payload))

    with pytest.raises(ReleasePreparationError, match="Sparse tar members are not supported"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert not (tmp_path / "source").exists()


def test_safe_extract_commit_source_rejects_old_gnu_sparse_member(tmp_path):
    archive_path = tmp_path / "old-gnu-sparse.tar.gz"
    raw_archive = io.BytesIO()
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(fileobj=raw_archive, mode="w", format=tarfile.GNU_FORMAT) as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(f"{root_name}/sparse.bin")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"X"))

    archive_bytes = bytearray(raw_archive.getvalue())
    sparse_header = bytearray(archive_bytes[tarfile.BLOCKSIZE : 2 * tarfile.BLOCKSIZE])
    sparse_header[156:157] = tarfile.GNUTYPE_SPARSE
    sparse_header[386:398] = b"00000000000\0"
    sparse_header[398:410] = b"00000000001\0"
    sparse_header[482:483] = b"\0"
    sparse_header[483:495] = b"00000000001\0"
    sparse_header[148:156] = b"        "
    checksum = tarfile.calc_chksums(sparse_header)[0]
    sparse_header[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    archive_bytes[tarfile.BLOCKSIZE : 2 * tarfile.BLOCKSIZE] = sparse_header
    archive_path.write_bytes(gzip.compress(archive_bytes))

    with pytest.raises(ReleasePreparationError, match="Sparse tar members are not supported"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert not (tmp_path / "source").exists()


def test_safe_extract_commit_source_rejects_nul_byte_in_pax_path(tmp_path):
    archive_path = tmp_path / "nul-path.tar.gz"
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(f"{root_name}/safe.txt")
        member.pax_headers = {"path": f"{root_name}/bad\0name"}
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(ReleasePreparationError, match="Unsafe commit source archive path"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)


def _make_oversized_metadata_archive(tmp_path, metadata_kind):
    root_name = f"knx_to_openhab-{_COMMIT[:12]}"
    metadata = "x" * (1024 * 1024 + 1)
    archive_path = tmp_path / f"{metadata_kind}.tar.gz"
    if metadata_kind in {"pax", "global-pax"}:
        archive_options = (
            {"pax_headers": {"comment": metadata}} if metadata_kind == "global-pax" else {}
        )
        with tarfile.open(
            archive_path,
            mode="w:gz",
            format=tarfile.PAX_FORMAT,
            **archive_options,
        ) as archive:
            root = tarfile.TarInfo(root_name)
            root.type = tarfile.DIRTYPE
            if metadata_kind == "pax":
                root.pax_headers = {"comment": metadata}
            archive.addfile(root)
    else:
        with tarfile.open(archive_path, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
            root = tarfile.TarInfo(root_name)
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
            if metadata_kind == "gnu-longname":
                member = tarfile.TarInfo(f"{root_name}/" + metadata)
                member.size = 0
                archive.addfile(member)
            else:
                member = tarfile.TarInfo(f"{root_name}/link")
                member.type = tarfile.SYMTYPE
                member.linkname = metadata
                archive.addfile(member)
    return archive_path


def _make_extended_header_chain_archive(tmp_path, header_type, payload, *, count=1100):
    archive_path = tmp_path / "deep-extended-headers.tar.gz"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for index in range(count):
            header = tarfile.TarInfo(f"extended-{index}")
            header.type = header_type
            header.size = len(payload)
            archive.addfile(header, io.BytesIO(payload))
        root = tarfile.TarInfo("knx_to_openhab-root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
    return archive_path


@pytest.mark.parametrize("metadata_kind", ["pax", "global-pax"])
def test_safe_extract_commit_source_rejects_oversized_pax_record(
    monkeypatch, tmp_path, metadata_kind
):
    archive_path = _make_oversized_metadata_archive(tmp_path, metadata_kind)
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", 2 * 1024 * 1024)

    with pytest.raises(ReleasePreparationError, match="Extended tar metadata exceeds"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert not (tmp_path / "source").exists()


def test_preflight_rejects_cumulative_global_pax_metadata(monkeypatch, tmp_path):
    def make_pax_record(key, value):
        body = f" {key}={value}\n".encode("ascii")
        record_length = len(body) + 1
        while True:
            record = str(record_length).encode("ascii") + body
            if len(record) == record_length:
                return record
            record_length = len(record)

    archive_path = tmp_path / "many-global-pax.tar.gz"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for index in range(2):
            payload = make_pax_record(f"comment{index}", "x" * 80)
            assert len(payload) < 128
            global_header = tarfile.TarInfo(f"global-{index}")
            global_header.type = tarfile.XGLTYPE
            global_header.size = len(payload)
            archive.addfile(global_header, io.BytesIO(payload))
        root = tarfile.TarInfo(f"knx_to_openhab-{_COMMIT[:12]}")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)

    monkeypatch.setattr(prepare_release_module, "_TAR_METADATA_LIMIT", 128)

    with pytest.raises(ReleasePreparationError, match="Cumulative global PAX metadata exceeds"):
        prepare_release_module._preflight_source_archive(archive_path)


@pytest.mark.parametrize(
    ("header_type", "payload"),
    [
        (tarfile.XHDTYPE, b"13 comment=x\n"),
        (tarfile.XGLTYPE, b"13 comment=x\n"),
        (tarfile.GNUTYPE_LONGNAME, b"long-name\0"),
        (tarfile.GNUTYPE_LONGLINK, b"link-target\0"),
    ],
    ids=("local-pax", "global-pax", "gnu-longname", "gnu-longlink"),
)
def test_preflight_rejects_excessive_consecutive_extended_headers(tmp_path, header_type, payload):
    archive_path = _make_extended_header_chain_archive(tmp_path, header_type, payload)

    with pytest.raises(ReleasePreparationError, match="Extended tar header chain exceeds") as error:
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert error.value.__cause__ is None
    assert not (tmp_path / "source").exists()


def test_preflight_normalizes_recursion_error_if_guard_is_not_reached(monkeypatch, tmp_path):
    archive_path = _make_extended_header_chain_archive(tmp_path, tarfile.XHDTYPE, b"13 comment=x\n")
    monkeypatch.setattr(prepare_release_module, "_TAR_EXTENDED_HEADER_CHAIN_LIMIT", 1200)

    with pytest.raises(ReleasePreparationError, match="Extended tar header chain exceeds") as error:
        prepare_release_module._preflight_source_archive(archive_path)

    assert isinstance(error.value.__cause__, RecursionError)


def test_preflight_rejects_cumulative_local_pax_metadata(monkeypatch, tmp_path):
    def make_pax_record(key, value):
        body = f" {key}={value}\n".encode("ascii")
        record_length = len(body) + 1
        while True:
            record = str(record_length).encode("ascii") + body
            if len(record) == record_length:
                return record
            record_length = len(record)

    archive_path = tmp_path / "many-local-pax.tar.gz"
    with tarfile.open(archive_path, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for index in range(2):
            payload = make_pax_record(f"comment{index}", "x" * 80)
            assert len(payload) < 128
            local_header = tarfile.TarInfo(f"local-{index}")
            local_header.type = tarfile.XHDTYPE
            local_header.size = len(payload)
            archive.addfile(local_header, io.BytesIO(payload))
        root = tarfile.TarInfo(f"knx_to_openhab-{_COMMIT[:12]}")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)

    monkeypatch.setattr(prepare_release_module, "_TAR_METADATA_LIMIT", 128)

    with pytest.raises(ReleasePreparationError, match="Cumulative local PAX metadata exceeds"):
        prepare_release_module._preflight_source_archive(archive_path)


@pytest.mark.parametrize("budget", ["member_count", "path_bytes"])
def test_preflight_rejects_archive_member_budget_exhaustion(monkeypatch, tmp_path, budget):
    archive_path = tmp_path / f"member-budget-{budget}.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo("root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo("root/file.txt")
        archive.addfile(member)

    if budget == "member_count":
        monkeypatch.setattr(prepare_release_module, "_ARCHIVE_MEMBER_LIMIT", 1, raising=False)
        expected_error = "Archive contains too many members"
    else:
        monkeypatch.setattr(prepare_release_module, "_ARCHIVE_PATH_BYTES_LIMIT", 3, raising=False)
        expected_error = "Archive member paths exceed the size limit"

    with pytest.raises(ReleasePreparationError, match=expected_error):
        prepare_release_module._preflight_source_archive(archive_path)


def test_release_extraction_rejects_member_count_budget_exhaustion(monkeypatch, tmp_path):
    archive_path, _checksum_path = _make_archive(tmp_path)
    monkeypatch.setattr(prepare_release_module, "_ARCHIVE_MEMBER_LIMIT", 1, raising=False)

    with pytest.raises(ReleasePreparationError, match="Archive contains too many members"):
        prepare_release_module._safe_extract(archive_path, tmp_path / "staged", _ROOT)


@pytest.mark.parametrize("malformation", ["checksum", "size"])
def test_preflight_rejects_malformed_header_after_valid_member(tmp_path, malformation):
    archive_path = tmp_path / f"malformed-{malformation}.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo("knx_to_openhab-root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)

    expanded = bytearray(gzip.decompress(archive_path.read_bytes()))
    malformed_header = bytearray(tarfile.BLOCKSIZE)
    malformed_header[:4] = b"evil"
    malformed_header[100:108] = b"0000644\0"
    malformed_header[156:157] = tarfile.REGTYPE
    if malformation == "size":
        malformed_header[124:136] = b"not-octal\0\0\0"
        malformed_header[148:156] = b"        "
        checksum = tarfile.calc_chksums(malformed_header)[0]
        malformed_header[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    expanded[tarfile.BLOCKSIZE : 2 * tarfile.BLOCKSIZE] = malformed_header
    archive_path.write_bytes(gzip.compress(expanded))

    with pytest.raises(ReleasePreparationError, match="Malformed tar header"):
        prepare_release_module._preflight_source_archive(archive_path)


def test_safe_extract_commit_source_rejects_oversized_gnu_long_name(monkeypatch, tmp_path):
    archive_path = _make_oversized_metadata_archive(tmp_path, "gnu-longname")
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", 2 * 1024 * 1024)

    with pytest.raises(ReleasePreparationError, match="Extended tar metadata exceeds"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert not (tmp_path / "source").exists()


def test_safe_extract_commit_source_rejects_oversized_gnu_long_link(monkeypatch, tmp_path):
    archive_path = _make_oversized_metadata_archive(tmp_path, "gnu-longlink")
    monkeypatch.setattr(prepare_release_module, "_EXPANDED_LIMIT", 2 * 1024 * 1024)

    with pytest.raises(ReleasePreparationError, match="Extended tar metadata exceeds"):
        prepare_release_module._safe_extract_commit_source(archive_path, tmp_path)

    assert not (tmp_path / "source").exists()
