"""Local-only source artifact and PEP503 fixture builders. No guest operations.

Run with ``python -B -m scripts.release_fixture_data --output NEW_DIRECTORY``.
Only exclusive staging and temporary native Git repositories are written.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

SOURCE_HEAD = "2dcf3078b61283a41fd1ef38e34327e4f759d5c1"
ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "diddip21/knx_to_openhab"
PHASES = ("stable-update", "no-update", "checksum-rejection", "migration-rejection", "retry")
MIGRATION_BODY = b"""    # Fixture-only CLI provenance; production helpers and migration tables unchanged.
    import sys

    if len(sys.argv) != 5 or sys.argv[1] != "--migrate-copy" or sys.argv[3] != "--output":
        raise SystemExit(74)
    marker = {
        "fixture": "copied-cli-migration-rejection-v1",
        "uid": getattr(os, "geteuid", lambda: None)(),
        "gid": getattr(os, "getegid", lambda: None)(),
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "co_filename": main.__code__.co_filename,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "intended_exit": 73,
    }
    raw = (json.dumps(marker, sort_keys=True) + "\\n").encode("ascii")
    if len(raw) > 2048:
        raise SystemExit(74)
    with Path(sys.argv[4]).with_name("fixture-migration-rejection.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    raise SystemExit(73)
"""
MAX_WHEEL = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(name):
    if (
        not isinstance(name, str)
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name) is None
    ):
        raise ValueError("Invalid project name")
    return re.sub(r"[-_.]+", "-", name).lower()


def read_regular(path, limit=MAX_WHEEL, owner=None):
    """Bounded, single-link, no-follow read with stable before/after identity."""
    path = Path(path).absolute()
    for ancestor in reversed(path.parents):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Noncanonical ancestor")
        if owner is not None and (info.st_uid != owner or info.st_mode & 0o022):
            raise ValueError("Unsafe owner/ancestor")
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > limit
        or getattr(before, "st_file_attributes", 0) & 0x400
    ):
        raise ValueError("Linked, nonregular or oversized file")
    if owner is not None and (before.st_uid != owner or before.st_mode & 0o022):
        raise ValueError("Unsafe file owner/mode")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")

    def unchanged(info):
        return all(getattr(before, field) == getattr(info, field) for field in fields)

    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not unchanged(os.fstat(stream.fileno())):
            raise ValueError("File changed before read")
        raw = stream.read(limit + 1)
        if not unchanged(os.fstat(stream.fileno())) or len(raw) != before.st_size:
            raise ValueError("File changed during read")
    # atime is allowed to change on POSIX reads.
    after = path.lstat()
    if not unchanged(after):
        raise ValueError("File changed after read")
    return raw


@dataclass(frozen=True)
class Wheel:
    filename: str
    project: str
    version: str
    requires_python: str | None
    body: bytes

    @property
    def sha256(self):
        return sha256(self.body)

    @property
    def path(self):
        return f"/packages/{self.sha256}/{self.filename}"


def requires_python_312(specifier):
    """Bounded numeric PEP440 subset used by this exact wheel snapshot.

    Unsupported (including prerelease/arbitrary) syntax refuses admission rather
    than guessing. This is not a dependency resolver or a packaging replacement.
    """
    actual = (3, 12, 3, 0)
    for clause in specifier.split(","):
        match = re.fullmatch(
            r"\s*(~=|==|!=|<=|>=|<|>)\s*([0-9]+(?:\.[0-9]+){0,3})(\.\*)?\s*", clause
        )
        if match is None:
            raise ValueError("Unsupported Requires-Python syntax")
        operator, version, wildcard = match.groups()
        parts = tuple(int(p) for p in version.split("."))
        target = (*parts, *((0,) * (4 - len(parts))))
        if wildcard:
            if operator not in ("==", "!="):
                raise ValueError("Invalid Requires-Python wildcard")
            equal = actual[: len(parts)] == parts
            accepted = equal if operator == "==" else not equal
        elif operator == "~=":
            if len(parts) < 2:
                raise ValueError("Invalid compatible Requires-Python")
            upper = (*parts[:-2], parts[-2] + 1)
            upper = (*upper, *((0,) * (4 - len(upper))))
            accepted = target <= actual < upper
        else:
            accepted = {
                "==": actual == target,
                "!=": actual != target,
                "<=": actual <= target,
                ">=": actual >= target,
                "<": actual < target,
                ">": actual > target,
            }[operator]
        if not accepted:
            raise ValueError("Requires-Python excludes actual target3.12.3")


def inspect_wheel(filename, raw):
    """Admit CPython3.12/Linux x86_64 wheels without importing wheel contents."""
    match = re.fullmatch(
        r"([A-Za-z0-9_.]+)-([A-Za-z0-9_.+!]+)(?:-[0-9][A-Za-z0-9_]*)?"
        r"-([a-z0-9_.]+)-([a-z0-9_.]+)-([a-z0-9_.]+)\.whl",
        filename,
    )
    if match is None or not 0 < len(raw) <= MAX_WHEEL:
        raise ValueError("Invalid wheel filename/size")
    name, version, python, abi, platform = match.groups()
    python_tags, abi_tags, platforms = python.split("."), abi.split("."), platform.split(".")
    compatible = False
    for py in python_tags:
        for ab in abi_tags:
            for plat in platforms:
                pure = py in ("py3", "py312", "cp312") and ab == "none" and plat == "any"
                linux = re.fullmatch(r"(?:manylinux(?:1|2010|2014|_2_[0-9]+)|linux)_x86_64", plat)
                floor = re.fullmatch(r"manylinux_2_([0-9]+)_x86_64", plat)
                if floor is not None and int(floor[1]) > 39:
                    linux = None  # Actual Noble target uses glibc2.39.
                native = linux and (
                    (py == "cp312" and ab in ("cp312", "abi3", "none"))
                    or (re.fullmatch(r"cp3(?:[2-9]|10|11)", py) and ab == "abi3")
                )
                compatible |= bool(pure or native)
    if not compatible:
        raise ValueError("Not a target-compatible wheel")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len({n.casefold() for n in names}) or len(names) > 30000:
                raise ValueError("Duplicate/excessive wheel members")
            if sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED:
                raise ValueError("Oversized expanded wheel")
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in info.filename
                    or ":" in info.filename
                    or info.flag_bits & 1
                    or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or str(path) != info.filename.rstrip("/")
                ):
                    raise ValueError("Unsafe wheel member")
            if archive.testzip() is not None:
                raise ValueError("Wheel CRC mismatch")
            metadata = [n for n in names if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Ambiguous top-level wheel metadata")
            prefix = metadata[0].split("/")[0]
            expected_prefix = f"{name}-{version}.dist-info"
            if prefix.casefold() != expected_prefix.casefold():
                raise ValueError("Wheel directory/filename mismatch")
            wheel_metadata = BytesParser().parsebytes(archive.read(prefix + "/WHEEL"))
            expected_tags = {
                f"{py}-{ab}-{plat}" for py in python_tags for ab in abi_tags for plat in platforms
            }
            if set(wheel_metadata.get_all("Tag", [])) != expected_tags:
                raise ValueError("WHEEL tags/filename mismatch")
            message = BytesParser().parsebytes(archive.read(metadata[0]))
            for field in ("Name", "Version"):
                if len(message.get_all(field, [])) != 1:
                    raise ValueError("Missing/duplicate wheel metadata")
            if normalize(message["Name"]) != normalize(name) or message["Version"] != version:
                raise ValueError("Wheel metadata/filename mismatch")
            requires = message.get_all("Requires-Python", [])
            if len(requires) > 1 or (requires and any(ord(c) < 32 for c in requires[0])):
                raise ValueError("Ambiguous Requires-Python")
            if requires:
                requires_python_312(requires[0])
            return Wheel(
                filename,
                normalize(message["Name"]),
                version,
                requires[0] if requires else None,
                raw,
            )
    except (
        zipfile.BadZipFile,
        KeyError,
        UnicodeError,
        RuntimeError,
        EOFError,
        zlib.error,
        NotImplementedError,
    ) as error:
        raise ValueError("Malformed wheel") from error


def inventory_wheels(directory, *, owner=None):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Canonical wheelhouse required")
    result = []
    for path in sorted(directory.iterdir()):
        if not path.name.endswith(".whl"):
            raise ValueError("Unknown wheelhouse entry")
        result.append(inspect_wheel(path.name, read_regular(path, owner=owner)))
    if not result or len(result) > 64:
        raise ValueError("Empty/excessive wheelhouse")
    index_routes(result)  # Also reject duplicate filename/route identities.
    return result


def index_routes(wheels):
    routes, projects, filenames = {}, {}, set()
    for item in wheels:
        if item.filename in filenames:
            raise ValueError("Duplicate wheel")
        filenames.add(item.filename)
        routes[("files.pythonhosted.org", item.path)] = ("application/octet-stream", item.body)
        requires = (
            f' data-requires-python="{html.escape(item.requires_python, quote=True)}"'
            if item.requires_python
            else ""
        )
        link = f"https://files.pythonhosted.org{item.path}#sha256={item.sha256}"
        projects.setdefault(item.project, []).append(
            f'<a href="{html.escape(link, quote=True)}"{requires}>{html.escape(item.filename)}</a>\n'
        )
    root = ""
    for name in sorted(projects):
        root += f'<a href="/simple/{name}/">{name}</a>\n'
        routes[("pypi.org", f"/simple/{name}/")] = (
            "text/html; charset=utf-8",
            ("<!doctype html>\n" + "".join(sorted(projects[name]))).encode(),
        )
    routes[("pypi.org", "/simple/")] = (
        "text/html; charset=utf-8",
        ("<!doctype html>\n" + root).encode(),
    )
    return routes


def git(*args, cwd=ROOT):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True).stdout


def source_files():
    """Verify every exported Git blob against the fixed reviewed commit's tree."""
    tree = {}
    for entry in git("ls-tree", "-r", "-z", SOURCE_HEAD).split(b"\0"):
        if entry:
            header, name = entry.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            path = name.decode("utf-8")
            if kind != "blob" or mode not in ("100644", "100755"):
                raise ValueError("Unsupported original source entry")
            tree[path] = (mode, oid)
    result = {}
    with tarfile.open(
        fileobj=io.BytesIO(git("-c", "core.autocrlf=false", "archive", "--format=tar", SOURCE_HEAD))
    ) as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or member.name not in tree:
                raise ValueError("Unexpected source export")
            raw = archive.extractfile(member).read()
            mode, oid = tree[member.name]
            if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != oid:
                raise ValueError("Original source blob mismatch")
            result[member.name] = (int(mode, 8), raw)
    if set(result) != set(tree):
        raise ValueError("Incomplete original source export")
    return result


def exclusive_staging(output):
    output = Path(output).absolute()
    for path in (output, *output.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Noncanonical staging ancestor")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    return output


def build_artifacts(output):
    output = exclusive_staging(output)
    original = source_files()
    manifest = {
        "source_head": SOURCE_HEAD,
        "source_files": {
            n: dict(mode=m, size=len(b), sha256=sha256(b)) for n, (m, b) in sorted(original.items())
        },
        "migration_cli_body": MIGRATION_BODY.decode(),
        "releases": {},
    }
    for label, version in (
        ("normal-0.1.1", "0.1.1"),
        ("normal-0.1.2", "0.1.2"),
        ("migration-negative", "0.1.2"),
    ):
        with tempfile.TemporaryDirectory(prefix="source-", dir=output) as temp:
            root = Path(temp)
            for name, (mode, body) in original.items():
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
                destination.chmod(0o755 if mode == 0o100755 else 0o644)
            (root / "VERSION").write_bytes((version + "\n").encode())
            if label == "migration-negative":
                path = root / "installer/config_migrations.py"
                body = path.read_bytes()
                marker = b"def main() -> None:\n"
                if body.count(marker) != 1:
                    raise ValueError("Original migration CLI marker changed")
                path.write_bytes(body.replace(marker, marker + MIGRATION_BODY))
            deltas = {}
            for name, (_, body) in original.items():
                changed = (root / name).read_bytes()
                if changed != body:
                    deltas[name] = dict(before=sha256(body), after=sha256(changed))
            expected = (
                {"VERSION", "installer/config_migrations.py"}
                if label == "migration-negative"
                else {"VERSION"}
            )
            if set(deltas) != expected:
                raise ValueError("Unexpected source delta")
            git("init", "--quiet", "--template=", cwd=root)
            git("config", "core.autocrlf", "false", cwd=root)
            git("add", "--all", "--force", cwd=root)
            executable = [name for name, (mode, _) in original.items() if mode == 0o100755]
            if executable:
                git("update-index", "--chmod=+x", "--", *executable, cwd=root)
            # Execute only the exported reviewed builder, not a local replacement.
            destination = output / label
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(root / "scripts/build_release.py"),
                    "--version",
                    version,
                    "--output-dir",
                    str(destination),
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            archive = destination / f"knx_to_openhab-{version}.tar.gz"
            with tarfile.open(archive, "r:gz") as bundle:
                members = bundle.getnames()
                archive_files = {
                    m.name: dict(
                        mode=m.mode, size=m.size, sha256=sha256(bundle.extractfile(m).read())
                    )
                    for m in bundle
                    if m.isfile()
                }
            manifest["releases"][label] = dict(
                version=version,
                archive=archive.name,
                size=archive.stat().st_size,
                sha256=sha256(archive.read_bytes()),
                deltas=deltas,
                members=members,
                archive_files=archive_files,
                sidecar_sha256=sha256((destination / (archive.name + ".sha256")).read_bytes()),
            )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def release_routes(directory, manifest, phase):
    if phase not in PHASES or manifest["source_head"] != SOURCE_HEAD:
        raise ValueError("Unsupported root-selected phase/source")
    label = {
        "stable-update": "normal-0.1.1",
        "no-update": "normal-0.1.1",
        "checksum-rejection": "normal-0.1.2",
        "migration-rejection": "migration-negative",
        "retry": "normal-0.1.2",
    }[phase]
    record = manifest["releases"][label]
    name, version = record["archive"], record["version"]
    routes, assets = {}, []
    for asset, field in ((name, "sha256"), (name + ".sha256", "sidecar_sha256")):
        body = read_regular(Path(directory) / label / asset)
        if sha256(body) != record[field]:
            raise ValueError("Release artifact hash mismatch")
        if phase == "checksum-rejection" and asset.endswith(".sha256"):
            body = f"{'0' * 64}  {name}\n".encode()
        path = f"/{REPOSITORY}/releases/download/v{version}/{asset}"
        routes[("github.com", path)] = ("application/octet-stream", body)
        assets.append(
            dict(name=asset, browser_download_url="https://github.com" + path, size=len(body))
        )
    latest = dict(tag_name="v" + version, draft=False, prerelease=False, assets=assets)
    routes[("api.github.com", f"/repos/{REPOSITORY}/releases/latest")] = (
        "application/json",
        json.dumps(latest, sort_keys=True).encode(),
    )
    return routes


def build_fixture(output, wheelhouse):
    """Seal complete local server data and trusted code; never packages private proof."""
    output = Path(output).absolute()
    wheels = inventory_wheels(wheelhouse)
    output = exclusive_staging(output)
    build_artifacts(output / "artifacts")
    (output / "wheels").mkdir(mode=0o700)
    for item in wheels:
        (output / "wheels" / item.filename).write_bytes(item.body)
    for name in ("release_fixture_data.py", "release_fixture_server.py"):
        shutil.copyfile(ROOT / "scripts" / name, output / name)
    files = {
        p.relative_to(output).as_posix(): dict(
            size=p.stat().st_size, sha256=sha256(read_regular(p))
        )
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    manifest = dict(
        format=1,
        source_head=SOURCE_HEAD,
        files=files,
        wheels=[
            dict(
                name=w.filename,
                project=w.project,
                version=w.version,
                size=len(w.body),
                sha256=w.sha256,
            )
            for w in wheels
        ],
    )
    (output / "fixture.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def load_fixture(directory, digest):
    directory = Path(directory)
    raw = read_regular(directory / "fixture.json")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or sha256(raw) != digest
    ):
        raise ValueError("Explicit fixture map pin mismatch")
    manifest = json.loads(raw)
    if (
        set(manifest) != {"format", "source_head", "files", "wheels"}
        or manifest["format"] != 1
        or manifest["source_head"] != SOURCE_HEAD
    ):
        raise ValueError("Unexpected fixture manifest")
    expected = {"fixture.json", *manifest["files"]}
    directories = {
        parent.as_posix()
        for name in manifest["files"]
        for parent in PurePosixPath(name).parents
        if str(parent) != "."
    }
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Linked fixture member")
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
        elif path.is_dir() and path.relative_to(directory).as_posix() not in directories:
            raise ValueError("Unknown fixture directory")
        elif not path.is_dir():
            raise ValueError("Nonregular fixture member")
    if actual != expected:
        raise ValueError("Incomplete/unknown fixture data")
    for name, value in manifest["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe fixture member")
        body = read_regular(directory / name)
        if value != dict(size=len(body), sha256=sha256(body)):
            raise ValueError("Fixture member mismatch")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args(argv)
    if args.wheelhouse is not None:
        build_fixture(args.output, args.wheelhouse)
        print("fixture.json SHA256:", sha256((args.output / "fixture.json").read_bytes()))
    else:
        manifest = build_artifacts(args.output)
        print(
            json.dumps(
                {label: r["sha256"] for label, r in manifest["releases"].items()}, sort_keys=True
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
