"""Standalone startup guard. Production: /usr/bin/python3 -I TRUSTED_SCRIPT ...

Installer wiring supplies canonical protected paths, never a service manifest.
Only a validated sibling libexec bundle is imported; candidate/current code and
the working directory are never placed on the import path.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import sys
from pathlib import Path


def check_start_allowed(paths, role):
    # Repository import for tests; standalone execution uses _trusted_core below.
    from .update_core.state import check_start_allowed as check

    return check(paths, role)


def _trusted_core(profile="guard"):
    if not sys.flags.isolated or os.name != "posix":
        raise ValueError("Guard requires isolated system Python on POSIX")
    script = Path(__file__)
    if not script.is_absolute() or ".." in script.parts:
        raise ValueError("Guard path must be absolute")
    bundle = script.parent
    names = ("__init__", "protocol", "secure_fs", "state")
    if profile == "coordinator":
        names += ("artifacts", "maintenance", "systemd", "transaction")
    elif profile != "guard":
        raise ValueError("Unknown fixed updater bundle profile")
    # Bootstrap cannot trust secure_fs until it has validated that module. All
    # ancestors and every imported source file are checked using no-follow FDs.
    files = [
        script,
        *(bundle / "update_core" / (name + ".py") for name in names),
    ]
    sources = {}
    for path in files:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            for index, component in enumerate(path.parts[1:]):
                info = os.fstat(fd)
                if info.st_uid != 0 or info.st_mode & 0o7022:
                    raise ValueError("Unsafe guard ancestor")
                leaf = index == len(path.parts) - 2
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
                if not leaf:
                    flags |= os.O_DIRECTORY
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if (
                info.st_uid != 0
                or info.st_mode & 0o7022
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise ValueError("Unsafe guard bundle file")
            if info.st_size > 1024 * 1024:
                raise ValueError("Oversized guard bundle source")
            raw = bytearray()
            while len(raw) <= 1024 * 1024:
                chunk = os.read(fd, min(65536, 1024 * 1024 + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(fd)
            attributes = (
                "st_dev",
                "st_ino",
                "st_uid",
                "st_gid",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if len(raw) > 1024 * 1024 or any(
                getattr(info, attr) != getattr(after, attr) for attr in attributes
            ):
                raise ValueError("Guard source changed while reading")
            sources[path] = bytes(raw)
        finally:
            os.close(fd)
    # Do not load pyc files, including root-unvalidated __pycache__ entries.
    package = "_knxoh_trusted_updater"
    spec = importlib.util.spec_from_file_location(
        package,
        bundle / "update_core/__init__.py",
        submodule_search_locations=[str(bundle / "update_core")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    # Compile validated sources explicitly: SourceFileLoader otherwise reads pyc.
    for name in names:
        fullname = package if name == "__init__" else package + "." + name
        if name != "__init__":
            module_spec = importlib.util.spec_from_file_location(
                fullname, bundle / f"update_core/{name}.py"
            )
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[fullname] = module
            setattr(sys.modules[package], name, module)
        source = bundle / f"update_core/{name}.py"
        exec(compile(sources[source], str(source), "exec"), module.__dict__)
    if profile == "coordinator":
        return sys.modules[package + ".transaction"]
    return (
        sys.modules[package + ".protocol"].Paths,
        sys.modules[package + ".state"].check_start_allowed,
    )


def main():
    if sys.argv[1:2] == ["--coordinator"]:
        try:
            return _trusted_core("coordinator").main(sys.argv[2:])
        except (OSError, ValueError, ImportError):
            return 1
    parser = argparse.ArgumentParser(description="Check the protected updater startup gate")
    parser.add_argument("--releases", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--role", required=True, choices=("ui", "cleanup"))
    args = parser.parse_args()
    try:
        paths_type, check = _trusted_core()
        return (
            0 if check(paths_type(args.releases, args.current, args.config_dir), args.role) else 1
        )
    except (OSError, ValueError, ImportError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
