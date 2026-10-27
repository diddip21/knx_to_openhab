import os
import shlex
from pathlib import PurePosixPath

import pytest

from installer.uninstall import UninstallError, resolve_uninstall_paths


def test_resolves_canonical_defaults_when_saved_paths_file_is_missing(tmp_path):
    paths = resolve_uninstall_paths({}, tmp_path / "missing-paths.env")

    assert paths.install_dir == PurePosixPath("/opt/knx_to_openhab")
    assert paths.config_dir == PurePosixPath("/etc/knx_to_openhab")
    assert paths.data_dir == PurePosixPath("/var/lib/knx_to_openhab")
    assert paths.backup_dir == PurePosixPath("/var/backups/knx_to_openhab")


def test_reads_quoted_paths_without_evaluating_shell_metacharacters(tmp_path):
    marker = tmp_path / "should-not-exist"
    paths_file = tmp_path / "paths.env"
    expected = f"/srv/knx app $cash 'quoted' ; touch {marker.as_posix()} \\path"
    paths_file.write_text(f"KNXOH_INSTALL_DIR={shlex.quote(expected)}\n", encoding="utf-8")

    paths = resolve_uninstall_paths({}, paths_file)

    assert str(paths.install_dir) == expected
    assert not marker.exists()


def test_environment_values_override_saved_paths(tmp_path):
    paths_file = tmp_path / "paths.env"
    paths_file.write_text('KNXOH_INSTALL_DIR="/srv/saved"\n', encoding="utf-8")

    paths = resolve_uninstall_paths({"KNXOH_INSTALL_DIR": "/srv/override"}, paths_file)

    assert paths.install_dir == PurePosixPath("/srv/override")


@pytest.mark.parametrize(
    "environment, match",
    [
        ({"KNXOH_INSTALL_DIR": "/"}, "filesystem root"),
        ({"KNXOH_INSTALL_DIR": "/etc"}, "system directory"),
        ({"KNXOH_INSTALL_DIR": "relative/install"}, "absolute"),
        ({"KNXOH_DATA_DIR": "/opt/knx_to_openhab/data"}, "overlap"),
        ({"KNXOH_BACKUP_DIR": "/var/lib/knx_to_openhab/jobs"}, "overlap"),
    ],
)
def test_rejects_unsafe_or_overlapping_paths_before_uninstall(tmp_path, environment, match):
    with pytest.raises(UninstallError, match=match):
        resolve_uninstall_paths(environment, tmp_path / "missing-paths.env")


@pytest.mark.skipif(os.name != "posix", reason="symlink path guard is POSIX-specific")
def test_rejects_symlinked_install_path(tmp_path):
    real_install = tmp_path / "real-install"
    real_install.mkdir()
    link = tmp_path / "install-link"
    link.symlink_to(real_install, target_is_directory=True)

    with pytest.raises(UninstallError, match="symlink"):
        resolve_uninstall_paths(
            {"KNXOH_INSTALL_DIR": str(link)},
            tmp_path / "missing-paths.env",
        )
