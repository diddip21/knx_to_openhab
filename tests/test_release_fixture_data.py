"""Portable fixture only: never imports application configuration or guest tools."""

import hashlib
import io
import json
import tarfile
import warnings
import zipfile

import pytest


def api():
    from scripts import release_fixture_data

    return release_fixture_data


def wheel(name="Flask", filename="flask-3.1.0-py3-none-any.whl", extra=()):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "flask-3.1.0.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 3.1.0\nRequires-Python: >=3.9\n\n",
        )
        archive.writestr("flask-3.1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
        archive.writestr("flask/__init__.py", "# real complete test wheel\n")
        for path, body in extra:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(path, body)
    return filename, stream.getvalue()


@pytest.mark.parametrize(
    "name,expected", [("Flask", "flask"), ("argon2_cffi", "argon2-cffi"), ("A.b_C", "a-b-c")]
)
def test_normalized_name(name, expected):
    assert api().normalize(name) == expected


@pytest.mark.parametrize("name", ["../bad", "", "a/b", "a?b", "-bad", "bad\n"])
def test_bad_names(name):
    with pytest.raises(ValueError):
        api().normalize(name)


def test_full_bytes_top_level_metadata_and_html():
    filename, raw = wheel(extra=[("flask/vendor/other.dist-info/METADATA", "Name: other\n")])
    item = api().inspect_wheel(filename, raw)
    assert item.project == "flask" and item.requires_python == ">=3.9"
    assert item.body == raw and item.sha256 == hashlib.sha256(raw).hexdigest()
    routes = api().index_routes([item])
    page = routes[("pypi.org", "/simple/flask/")][1].decode()
    assert f"https://files.pythonhosted.org/packages/{item.sha256}/{filename}" in page
    assert f"#sha256={item.sha256}" in page and 'data-requires-python="&gt;=3.9"' in page
    assert routes[("files.pythonhosted.org", item.path)][1] == raw
    assert b"flask" in routes[("pypi.org", "/simple/")][1]


@pytest.mark.parametrize(
    "filename,raw",
    [
        ("flask-3.1.0-py3-none-any.whl", b"not zip"),
        wheel(name="different"),
        ("flask-3.2.0-py3-none-any.whl", wheel()[1]),
        ("../flask-3.1.0-py3-none-any.whl", wheel()[1]),
        wheel(extra=[("../escape", "bad")]),
        wheel(extra=[("flask-3.1.0.dist-info/METADATA", "Name: flask\nVersion: 3.1.0\n")]),
        wheel(extra=[("other-1.dist-info/METADATA", "Name: other\nVersion: 1\n")]),
        ("flask-3.1.0-cp311-cp311-win_amd64.whl", wheel()[1]),
    ],
)
def test_reject_invalid_wheels(filename, raw):
    with pytest.raises(ValueError):
        api().inspect_wheel(filename, raw)


def test_duplicate_wheel_routes_refused():
    item = api().inspect_wheel(*wheel())
    with pytest.raises(ValueError):
        api().index_routes([item, item])


def test_inventory_refuses_links_and_unknown_entries(tmp_path):
    filename, raw = wheel()
    (tmp_path / filename).write_bytes(raw)
    assert api().inventory_wheels(tmp_path)[0].body == raw
    (tmp_path / "unexpected.txt").write_text("no")
    with pytest.raises(ValueError):
        api().inventory_wheels(tmp_path)


def test_builds_exact_source_reproducibly_and_records_all_deltas(tmp_path):
    first = api().build_artifacts(tmp_path / "first")
    second = api().build_artifacts(tmp_path / "second")
    assert first == second
    assert first["source_head"] == "2dcf3078b61283a41fd1ef38e34327e4f759d5c1"
    for label, record in first["releases"].items():
        folder = tmp_path / "first" / label
        archive = folder / record["archive"]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == record["sha256"]
        assert record["deltas"].keys() == (
            {"VERSION", "installer/config_migrations.py"}
            if label == "migration-negative"
            else {"VERSION"}
        )
        with tarfile.open(archive, "r:gz") as bundle:
            names = bundle.getnames()
            assert names == record["members"]
            requirements = bundle.extractfile(
                f"knx_to_openhab-{record['version']}/requirements.txt"
            )
            assert hashlib.sha256(requirements.read()).hexdigest() == (
                "836f5d08439f7a536cae171993c199821a95d1face231826a49bb0043a5829fe"
            )
            assert not any(".whl" in n or "receipt" in n or "private" in n for n in names)
        assert (folder / (record["archive"] + ".sha256")).read_text().startswith(record["sha256"])
    assert json.loads((tmp_path / "first" / "manifest.json").read_text()) == first
    with pytest.raises(FileExistsError):
        api().build_artifacts(tmp_path / "first")


def test_staging_symlink_refused(tmp_path):
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Native symlink privilege unavailable")
    with pytest.raises((ValueError, FileExistsError)):
        api().build_artifacts(link)


def test_release_routes_original_urls_and_negative_sidecar(tmp_path):
    manifest = api().build_artifacts(tmp_path / "artifacts")
    stable = api().release_routes(tmp_path / "artifacts", manifest, "stable-update")
    bad = api().release_routes(tmp_path / "artifacts", manifest, "checksum-rejection")
    latest = ("api.github.com", "/repos/diddip21/knx_to_openhab/releases/latest")
    assert json.loads(stable[latest][1])["tag_name"] == "v0.1.1"
    assert json.loads(bad[latest][1])["tag_name"] == "v0.1.2"
    for route, (_, body) in bad.items():
        if route[1].endswith(".sha256"):
            assert body.startswith(b"0" * 64)
        elif route[1].endswith(".tar.gz"):
            assert (
                hashlib.sha256(body).hexdigest() == manifest["releases"]["normal-0.1.2"]["sha256"]
            )
    with pytest.raises(ValueError):
        api().release_routes(tmp_path / "artifacts", manifest, "client-selected-phase")


def test_fixture_complete_map_and_tamper_refusal(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    name, raw = wheel()
    (wheels / name).write_bytes(raw)
    fixture = tmp_path / "fixture"
    manifest = api().build_fixture(fixture, wheels)
    digest = api().sha256((fixture / "fixture.json").read_bytes())
    assert api().load_fixture(fixture, digest) == manifest
    assert "release_fixture_server.py" in manifest["files"]
    assert "release_fixture_data.py" in manifest["files"]
    assert len(manifest["wheels"]) == 1
    (fixture / "wheels" / name).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        api().load_fixture(fixture, digest)


@pytest.mark.parametrize("specifier", [">=4", "<3.12", "!=3.12.*", ">=oops", '>=3.9" onclick="bad'])
def test_invalid_or_incompatible_requires_python(specifier):
    filename, raw = wheel()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as before, zipfile.ZipFile(out, "w") as after:
        for info in before.infolist():
            body = before.read(info)
            if info.filename.endswith("/METADATA"):
                body = body.replace(b">=3.9", specifier.encode())
            after.writestr(info, body)
    with pytest.raises(ValueError):
        api().inspect_wheel(filename, out.getvalue())


def test_inventory_refuses_hardlinks(tmp_path):
    import os

    name, raw = wheel()
    path = tmp_path / name
    path.write_bytes(raw)
    os.link(path, tmp_path / "second.whl")
    with pytest.raises(ValueError):
        api().inventory_wheels(tmp_path)


def test_fixture_refuses_unknown_empty_directory(tmp_path):
    root = tmp_path / "fixture"
    root.mkdir()
    manifest = dict(format=1, source_head=api().SOURCE_HEAD, files={}, wheels=[])
    raw = json.dumps(manifest).encode()
    (root / "fixture.json").write_bytes(raw)
    (root / "unknown").mkdir()
    with pytest.raises(ValueError):
        api().load_fixture(root, api().sha256(raw))


def test_rejects_wheel_requiring_newer_glibc_than_actual_noble():
    _, raw = wheel()
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as before, zipfile.ZipFile(stream, "w") as after:
        for info in before.infolist():
            body = before.read(info)
            if info.filename.endswith("/WHEEL"):
                body = body.replace(b"py3-none-any", b"cp312-cp312-manylinux_2_99_x86_64")
            after.writestr(info, body)
    with pytest.raises(ValueError):
        api().inspect_wheel("flask-3.1.0-cp312-cp312-manylinux_2_99_x86_64.whl", stream.getvalue())


def test_staging_refuses_windows_reparse_ancestor(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    original = Path.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == tmp_path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse)
    output = tmp_path / "must-not-create"
    with pytest.raises(ValueError):
        api().build_artifacts(output)
    assert not output.exists()
