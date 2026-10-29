"""Unprivileged maintenance facade; never provisions privileged updater files.

Legacy/dev mode is the flat local-config layout, NOT FLASK_ENV. External config
or a canonical releases layout fails closed if provisioning is absent, including
when a release worker was accidentally launched without its path environment.
"""

from contextlib import contextmanager
from functools import wraps

from installer.update_core import maintenance as core
from installer.update_core.protocol import Paths
from installer.update_core.state import check_start_allowed
from knxoh_paths import InstallPaths, get_paths

MaintenanceError = core.MaintenanceError


def _protected_install(paths):
    return (
        paths.secrets_file is not None
        or paths.project_root.parent == paths.install_dir / "releases"
    )


@contextmanager
def mutation_lease(paths: InstallPaths):
    if not _protected_install(paths):
        yield
    else:
        with core.mutation_lease(paths):
            yield


def maintenance_requested(paths: InstallPaths) -> bool:
    return _protected_install(paths) and core.maintenance_requested(paths)


def guarded_mutation(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with mutation_lease(get_paths()):
            return function(*args, **kwargs)

    return guarded


def readiness_version(paths):
    """Read source VERSION, never Git; a stale worker is not current readiness."""
    source = paths.project_root
    if _protected_install(paths):
        protected = Paths(
            paths.install_dir / "releases", paths.install_dir / "current", paths.config_dir
        )
        if protected.current.resolve(strict=True) != source.resolve(strict=True):
            raise ValueError("Worker is not the active release")
        if not check_start_allowed(protected, "ui"):
            raise ValueError("Recovery gate denies readiness")
    version = (source / "VERSION").read_text(encoding="ascii").strip()
    if not version or len(version) > 128 or any(c.isspace() for c in version):
        raise ValueError("Invalid source version")
    return version
