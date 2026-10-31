import json
import os
import stat

import pytest

from installer import provision_managed_outputs as provisioner
from installer.provision_managed_outputs import (
    ProvisionError,
    provision_managed_yaml,
    validate_managed_yaml_target,
)


def _owner_ids():
    return getattr(os, "getuid", lambda: 0)(), getattr(os, "getgid", lambda: 0)()


def test_provisioning_creates_only_the_requested_yaml_target(tmp_path):
    openhab_root = tmp_path / "openhab"
    openhab_root.mkdir()
    target = openhab_root / "yaml" / "knx.yaml"
    uid, gid = _owner_ids()

    provision_managed_yaml(openhab_root, target, uid, gid)

    assert target.is_file()
    assert target.read_text(encoding="utf-8") == ""
    assert not (openhab_root / "items").exists()
    if os.name == "posix":
        info = target.stat()
        assert stat.S_IMODE(info.st_mode) == 0o640
        assert info.st_uid == uid
        assert info.st_gid == gid


def test_provisioning_preserves_existing_yaml_contents(tmp_path):
    openhab_root = tmp_path / "openhab"
    yaml_dir = openhab_root / "yaml"
    yaml_dir.mkdir(parents=True)
    target = yaml_dir / "knx.yaml"
    target.write_text("existing generated model\n", encoding="utf-8")
    uid, gid = _owner_ids()

    provision_managed_yaml(openhab_root, target, uid, gid)

    assert target.read_text(encoding="utf-8") == "existing generated model\n"


@pytest.mark.parametrize(
    "target_factory",
    [
        lambda root, tmp_path: root / "yaml" / ".." / "items" / "knx.yaml",
        lambda root, tmp_path: root / "items" / "knx.yaml",
        lambda root, tmp_path: root / "yaml" / "knx.items",
        lambda root, tmp_path: tmp_path / "manual.yaml",
    ],
    ids=("traversal", "non-yaml-directory", "wrong-extension", "outside-openhab"),
)
def test_provisioning_rejects_non_managed_yaml_targets(tmp_path, target_factory):
    openhab_root = tmp_path / "openhab"
    openhab_root.mkdir()
    target = target_factory(openhab_root, tmp_path)
    uid, gid = _owner_ids()

    with pytest.raises(ProvisionError):
        provision_managed_yaml(openhab_root, target, uid, gid)


def test_target_validation_resolves_default_relative_yaml_path(tmp_path):
    install_root = tmp_path / "app"
    openhab_root = install_root / "openhab"

    target = validate_managed_yaml_target(openhab_root, install_root, "openhab/yaml/knx.yaml")

    assert target == openhab_root / "yaml" / "knx.yaml"


def test_runtime_target_uses_protected_openhab_root_and_validates_generator_path(
    monkeypatch, tmp_path
):
    install_root = tmp_path / "app"
    config_dir = tmp_path / "etc"
    data_dir = tmp_path / "data"
    openhab_root = tmp_path / "openhab"
    config_dir.mkdir()
    data_dir.mkdir()
    openhab_root.mkdir()
    (config_dir / "managed_openhab_root").write_text(f"{openhab_root}\n", encoding="utf-8")
    (data_dir / "generator.json").write_text(
        json.dumps({"yaml_path": str(openhab_root / "yaml" / "knx.yaml")}), encoding="utf-8"
    )
    monkeypatch.setattr(provisioner, "_require_protected_directory", lambda *_args: None)
    monkeypatch.setattr(provisioner, "_require_protected_file", lambda *_args: None)
    monkeypatch.setattr(provisioner, "_require_trusted_directory_chain", lambda *_args: None)
    paths = {
        "KNXOH_INSTALL_DIR": install_root,
        "KNXOH_CONFIG_DIR": config_dir,
        "KNXOH_DATA_DIR": data_dir,
    }

    resolved_root, target = provisioner._configured_target(paths, service_uid=1234)

    assert resolved_root == openhab_root
    assert target == openhab_root / "yaml" / "knx.yaml"

    (data_dir / "generator.json").write_text(
        json.dumps({"yaml_path": str(tmp_path / "outside" / "knx.yaml")}), encoding="utf-8"
    )
    with pytest.raises(ProvisionError, match="YAML target"):
        provisioner._configured_target(paths, service_uid=1234)


def test_provisioning_rejects_symlinked_yaml_directory(tmp_path):
    openhab_root = tmp_path / "openhab"
    openhab_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (openhab_root / "yaml").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    uid, gid = _owner_ids()
    with pytest.raises(ProvisionError):
        provision_managed_yaml(openhab_root, openhab_root / "yaml" / "knx.yaml", uid, gid)

    assert not (outside / "knx.yaml").exists()


def test_provisioning_rejects_symlinked_yaml_target(tmp_path):
    openhab_root = tmp_path / "openhab"
    yaml_dir = openhab_root / "yaml"
    yaml_dir.mkdir(parents=True)
    outside = tmp_path / "outside.yaml"
    outside.write_text("do not touch", encoding="utf-8")
    target = yaml_dir / "knx.yaml"
    try:
        target.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")

    uid, gid = _owner_ids()
    with pytest.raises(ProvisionError):
        provision_managed_yaml(openhab_root, target, uid, gid)

    assert outside.read_text(encoding="utf-8") == "do not touch"
