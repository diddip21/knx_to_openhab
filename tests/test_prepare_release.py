import hashlib
import io
import json
import tarfile

import pytest

from installer.prepare_release import (
    ReleasePreparationError,
    prepare_release,
    verify_and_extract,
)

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


def test_prepare_release_downloads_expected_https_assets_and_cleans_staging(
    monkeypatch, tmp_path
):
    archive_path, checksum_path = _make_archive(tmp_path, version="1.2.3+build.1")
    requested_urls = []

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
    assert all(url.startswith("https://github.com/diddip21/knx_to_openhab/releases/download/") for url in requested_urls)
    assert "%2B" in requested_urls[0]
    assert not list(tmp_path.glob(".assets-*"))
