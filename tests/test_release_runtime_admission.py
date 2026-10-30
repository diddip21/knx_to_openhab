"""Portable diagnostic tests, NOT successful update or disposable-guest evidence."""

import ast
import hashlib
import os

import pytest

from scripts import check_release_runtime_admission as diagnostic


@pytest.fixture(scope="module")
def reviewed_source():
    raw = diagnostic.reviewed_helper()
    # Exact original reviewed production bytes, not a harness-selected helper.
    assert hashlib.sha256(raw).hexdigest() == (
        "260b76e82ca6ab712a84362a0f022d783db62f6e2b114fe442da8a2229a3106f"
    )
    return raw


def test_reviewed_production_requires_null_config_and_isolated_full_install(reviewed_source):
    assert diagnostic.dependency_environment(reviewed_source) == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": "/tmp",
        "PIP_CONFIG_FILE": "/dev/null",
    }
    tree = ast.parse(reviewed_source)
    function = next(
        node for node in tree.body if getattr(node, "name", None) == "prepare_dependencies"
    )
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    runner_calls = [
        node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "runner"
    ]
    assert len(runner_calls) == 2
    literals = [
        [part.value for part in node.args[0].elts if isinstance(part, ast.Constant)]
        for node in runner_calls
    ]
    assert literals == [
        ["/usr/bin/python3", "-I", "-m", "venv", "--copies"],
        [
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "-r",
        ],
    ]


def test_real_pip_blocks_requested_offline_admission(tmp_path, reviewed_source):
    observation = diagnostic.probe_pip_configuration(tmp_path)
    result = diagnostic.admission(reviewed_source, observation)
    assert result["admitted"] is False
    assert result["actual_guest_update_verified"] is False
    assert observation["positive_control_exit"] == 0
    assert observation["null_device_exit"] == 1
    assert "suppresses /etc/pip.conf" in result["reason"]
    # The only settings file belongs to this new disposable local venv.
    config = tmp_path / "venv" / ("pip.ini" if os.name == "nt" else "pip.conf")
    assert config.read_text() == "[global]\nno-index = true\n"


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_unknown_diagnostic_tree_refused_before_any_process(tmp_path, monkeypatch, kind):
    venv = tmp_path / "venv"
    if kind == "directory":
        venv.mkdir()
    elif kind == "file":
        venv.write_bytes(b"not ours")
    else:
        try:
            venv.symlink_to(tmp_path / "absent", target_is_directory=True)
        except OSError:
            pytest.skip("Native symlink privilege unavailable")
    monkeypatch.setattr(
        diagnostic.subprocess, "run", lambda *a, **k: pytest.fail("unexpected subprocess")
    )
    with pytest.raises(ValueError, match="Fresh"):
        diagnostic.probe_pip_configuration(tmp_path)
    assert os.path.lexists(venv)


@pytest.mark.parametrize(
    "args",
    [["--phase", "update"], ["--destination", "Ubuntu"], ["--repair"], ["--help", "--update"]],
)
def test_no_runtime_phase_or_destination_override(args, monkeypatch):
    monkeypatch.setattr(diagnostic, "reviewed_helper", lambda: pytest.fail("source read"))
    with pytest.raises(SystemExit):
        diagnostic.main(args)


def test_changed_production_is_not_implicitly_adopted(reviewed_source):
    changed = reviewed_source.replace(b'"PIP_CONFIG_FILE": "/dev/null"', b'"PIP_CONFIG_FILE": ""')
    with pytest.raises(ValueError, match="Reviewed helper changed"):
        diagnostic.admission(changed, {})
