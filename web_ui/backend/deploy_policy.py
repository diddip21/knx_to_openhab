"""Path and file-descriptor checks for generated OpenHAB output files."""

import os
import shutil
import stat
import tarfile
from pathlib import PurePosixPath


class DeployPolicyError(ValueError):
    """Raised when a staged deployment escapes the managed output boundary."""


OUTPUT_SPECS = {
    "items_path": ("items", ".items"),
    "things_path": ("things", ".things"),
    "sitemaps_path": ("sitemaps", ".sitemap"),
    "influx_path": ("persistence", ".persist"),
    "fenster_path": ("rules", ".rules"),
    "yaml_path": ("yaml", ".yaml"),
}

REPORT_NAMES = (
    "unknown_report.json",
    "partial_report.json",
    "completeness_report.json",
)

_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _path_text(value, label):
    if not isinstance(value, (str, os.PathLike)):
        raise DeployPolicyError(f"{label} must be a filesystem path")
    path = os.fspath(value)
    if not path or "\x00" in path or "\\" in path:
        raise DeployPolicyError(f"{label} is not a valid POSIX path")
    if ".." in PurePosixPath(path).parts:
        raise DeployPolicyError(f"{label} must not contain traversal components")
    return path


def _absolute_path(value, base_dir, label):
    path = _path_text(value, label)
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    return os.path.abspath(path)


def _relative_path(path, root, label):
    try:
        relative = os.path.relpath(path, root)
    except ValueError as error:
        raise DeployPolicyError(f"{label} must be under the OpenHAB configuration root") from error

    parts = PurePosixPath(relative.replace(os.sep, "/")).parts
    if not parts or relative == "." or any(part in (".", "..") for part in parts):
        raise DeployPolicyError(f"{label} must be under the OpenHAB configuration root")
    return "/".join(parts)


def configured_managed_paths(config, project_root):
    """Return the canonical OpenHAB root and configured managed output paths.

    Generator outputs are limited to one file directly inside their documented
    OpenHAB directory. Reports are fixed files in the configuration root.
    """
    root_value = config.get("openhab_path", "openhab")
    root = _absolute_path(root_value, project_root, "openhab_path")
    root = os.path.realpath(root)
    project_root = os.path.realpath(os.path.abspath(project_root))
    if root in {"/", "/etc", "/usr", "/var", "/opt", "/home", "/root", "/tmp"}:
        raise DeployPolicyError("openhab_path must name a dedicated configuration directory")
    try:
        inside_project = os.path.commonpath([root, project_root]) == project_root
    except ValueError:
        inside_project = False
    if inside_project and root != os.path.join(project_root, "openhab"):
        raise DeployPolicyError("openhab_path inside the application must be the openhab directory")
    managed = {}

    for key, (directory, suffix) in OUTPUT_SPECS.items():
        value = config.get(key)
        if not value:
            continue
        target = _absolute_path(value, project_root, key)
        relative = _relative_path(target, root, key)
        parts = PurePosixPath(relative).parts
        if len(parts) != 2 or parts[0] != directory:
            raise DeployPolicyError(f"{key} must target one file directly inside {directory}/")
        if not parts[1].endswith(suffix) or parts[1] in (".", ".."):
            raise DeployPolicyError(f"{key} must use the {suffix} file extension")
        managed[key] = relative

    for name in REPORT_NAMES:
        managed[name] = name

    if len(set(managed.values())) != len(managed):
        raise DeployPolicyError("Managed output paths must be unique")
    return root, managed


def _open_directory(root, relative_directory="", create=False, group_id=None):
    """Open a directory tree without following symlinks in its components."""
    current_fd = os.open(root, _DIRECTORY_FLAGS | _NOFOLLOW)
    try:
        if create and group_id is not None:
            info = os.fstat(current_fd)
            os.fchown(current_fd, info.st_uid, group_id)
            os.fchmod(current_fd, (stat.S_IMODE(info.st_mode) & ~0o020) | 0o050)
        parts = () if not relative_directory else PurePosixPath(relative_directory).parts
        for part in parts:
            if part in ("", ".", ".."):
                raise DeployPolicyError("Directory path contains an unsafe component")
            try:
                next_fd = os.open(
                    part,
                    _DIRECTORY_FLAGS | _NOFOLLOW,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=current_fd)
                next_fd = os.open(
                    part,
                    _DIRECTORY_FLAGS | _NOFOLLOW,
                    dir_fd=current_fd,
                )
            if create and group_id is not None:
                info = os.fstat(next_fd)
                os.fchown(next_fd, info.st_uid, group_id)
                os.fchmod(next_fd, (stat.S_IMODE(info.st_mode) & ~0o020) | 0o050)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_regular_file(root, relative_path, flags):
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise DeployPolicyError("File path contains an unsafe component")

    parent_fd = _open_directory(root, "/".join(parts[:-1]))
    try:
        fd = os.open(parts[-1], flags | _NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DeployPolicyError(f"Managed target is not a regular file: {relative_path}")
        if info.st_nlink != 1:
            raise DeployPolicyError(f"Managed target must not be a hard link: {relative_path}")
        return fd
    except Exception:
        os.close(fd)
        raise


def provision_managed_files(root, managed_paths, uid, gid, mode=0o640):
    """Create missing generated files and grant one service user ownership."""
    root = os.path.realpath(os.path.abspath(root))
    for relative in sorted(set(managed_paths.values())):
        parts = PurePosixPath(relative).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise DeployPolicyError(f"Unsafe managed path: {relative}")
        parent_fd = _open_directory(root, "/".join(parts[:-1]), create=True, group_id=gid)
        try:
            try:
                fd = os.open(
                    parts[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                    mode,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                fd = os.open(parts[-1], os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)

            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise DeployPolicyError(
                        f"Managed target must be a single-link regular file: {relative}"
                    )
                os.fchown(fd, uid, gid)
                os.fchmod(fd, mode)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)


def restrict_service_write_access(root, service_uid):
    """Remove broad group/other writes and service-owned non-output files."""
    root = os.path.realpath(os.path.abspath(root))

    def fail_walk(error):
        raise error

    def secure_path(path):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            return
        if info.st_uid == service_uid and service_uid != 0:
            os.chown(path, 0, -1, follow_symlinks=False)
            info = os.lstat(path)
        mode = stat.S_IMODE(info.st_mode) & ~0o022
        if mode != stat.S_IMODE(info.st_mode):
            os.chmod(path, mode, follow_symlinks=False)

    secure_path(root)
    for current, directories, files in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in [*directories, *files]:
            secure_path(os.path.join(current, name))


def _copy_file_descriptors(source_fd, target_fd):
    os.lseek(source_fd, 0, os.SEEK_SET)
    os.ftruncate(target_fd, 0)
    os.lseek(target_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(source_fd), "rb") as source:
        with os.fdopen(os.dup(target_fd), "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())


def _read_all(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _replace_file_contents(fd, content):
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = memoryview(content)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("Short write while restoring managed file")
        remaining = remaining[written:]
    os.fsync(fd)


def _managed_relative_path(relative_path, managed_paths):
    relative = _path_text(relative_path, "managed target")
    path = PurePosixPath(relative)
    raw_parts = relative.split("/")
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in raw_parts):
        raise DeployPolicyError("Managed target must be a safe relative path")
    relative = path.as_posix()
    if relative not in set(managed_paths.values()):
        raise DeployPolicyError(f"Managed target is not managed: {relative}")
    return relative


def read_managed_file(openhab_root, relative_path, managed_paths):
    """Read an existing single-link managed file without following symlinks."""
    relative = _managed_relative_path(relative_path, managed_paths)
    root = os.path.realpath(os.path.abspath(openhab_root))

    if os.name == "nt":
        current = root
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            current = os.path.join(current, part)
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise DeployPolicyError(f"Managed path must not contain symlinks: {relative}")
        target = os.path.join(current, parts[-1])
        if stat.S_ISLNK(os.lstat(target).st_mode):
            raise DeployPolicyError(f"Managed target must not be a symlink: {relative}")
        descriptor = os.open(target, os.O_RDONLY | _NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise DeployPolicyError(f"Managed target is not a regular file: {relative}")
            if info.st_nlink != 1:
                raise DeployPolicyError(f"Managed target must not be a hard link: {relative}")
            return _read_all(descriptor)
        finally:
            os.close(descriptor)

    descriptor = _open_regular_file(root, relative, os.O_RDONLY)
    try:
        return _read_all(descriptor)
    finally:
        os.close(descriptor)


def write_managed_file(openhab_root, relative_path, content, managed_paths):
    """Replace one already-provisioned managed regular file and fsync its inode."""
    if not isinstance(content, bytes):
        raise TypeError("Managed file content must be bytes")
    relative = _managed_relative_path(relative_path, managed_paths)
    root = os.path.realpath(os.path.abspath(openhab_root))
    descriptor = _open_regular_file(root, relative, os.O_WRONLY)
    try:
        _replace_file_contents(descriptor, content)
    finally:
        os.close(descriptor)


def deploy_staged_files(mapping, staging_dir, openhab_root, managed_paths):
    """Copy only configured managed files into already provisioned inodes.

    The target directory is never created or modified. Existing regular files
    are opened with ``O_NOFOLLOW`` and written in place so the service account
    needs write access only to the exact generated files.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise DeployPolicyError("No staged files found")

    staging_dir = os.path.abspath(staging_dir)
    openhab_root = os.path.realpath(os.path.abspath(openhab_root))
    allowed = set(managed_paths.values())
    opened = []
    seen = set()

    try:
        for staged_value, target_value in mapping.items():
            staged = _absolute_path(staged_value, staging_dir, "staged file")
            target = _absolute_path(target_value, openhab_root, "deployment target")
            staged_relative = _relative_path(
                staged, os.path.join(staging_dir, "openhab"), "staged file"
            )
            target_relative = _relative_path(target, openhab_root, "deployment target")

            if target_relative not in allowed:
                raise DeployPolicyError(f"Deployment target is not managed: {target_relative}")
            if target_relative != staged_relative:
                raise DeployPolicyError("Staged file does not match its managed target")
            if target_relative in seen:
                raise DeployPolicyError(f"Duplicate deployment target: {target_relative}")
            seen.add(target_relative)

            source_fd = _open_regular_file(
                os.path.join(staging_dir, "openhab"), staged_relative, os.O_RDONLY
            )
            try:
                target_fd = _open_regular_file(openhab_root, target_relative, os.O_WRONLY)
            except Exception:
                os.close(source_fd)
                raise
            opened.append((source_fd, target_fd, target_relative))

        for source_fd, target_fd, _relative in opened:
            _copy_file_descriptors(source_fd, target_fd)
    finally:
        for source_fd, target_fd, _relative in opened:
            os.close(source_fd)
            os.close(target_fd)

    return len(opened)


def restore_managed_files(backup_path, openhab_root, managed_relatives):
    """Restore available managed regular files from a full-directory tar backup.

    Archive contents and current target contents are read before any live file is
    changed. If a write fails, the saved target contents are written back.
    """
    openhab_root = os.path.realpath(os.path.abspath(openhab_root))
    archive_root = os.path.basename(os.path.normpath(openhab_root))
    staged_contents = {}

    # Read and validate every available archive entry before opening any live
    # file for writing. Older backups can lack some of today's managed outputs.
    with tarfile.open(backup_path, "r:gz") as archive:
        for relative in sorted(set(managed_relatives)):
            _path_text(relative, "backup target")
            if (
                _relative_path(os.path.join(openhab_root, relative), openhab_root, "backup target")
                != relative
            ):
                raise DeployPolicyError("Backup target is not a managed relative path")
            member_name = f"{archive_root}/{relative}"
            try:
                member = archive.getmember(member_name)
            except KeyError:
                continue
            if not member.isfile():
                raise DeployPolicyError(f"Backup entry is not a regular file: {relative}")
            source = archive.extractfile(member)
            if source is None:
                raise DeployPolicyError(f"Could not read backup entry: {relative}")
            with source:
                staged_contents[relative] = source.read()

    if not staged_contents:
        return 0

    opened = []
    try:
        for relative in sorted(staged_contents):
            target_fd = _open_regular_file(openhab_root, relative, os.O_RDWR)
            try:
                original = _read_all(target_fd)
            except Exception:
                os.close(target_fd)
                raise
            opened.append((relative, target_fd, original))

        touched = []
        try:
            for relative, target_fd, _original in opened:
                touched.append((relative, target_fd, _original))
                _replace_file_contents(target_fd, staged_contents[relative])
        except Exception as write_error:
            recovery_errors = []
            for relative, target_fd, original in touched:
                try:
                    _replace_file_contents(target_fd, original)
                except Exception as recovery_error:
                    recovery_errors.append(f"{relative}: {recovery_error}")
            if recovery_errors:
                raise DeployPolicyError(
                    "Restore failed and one or more live files could not be recovered: "
                    + "; ".join(recovery_errors)
                ) from write_error
            raise
    finally:
        for _relative, target_fd, _original in opened:
            os.close(target_fd)

    return len(opened)
