"""Local-only admission diagnostic; NEVER invokes WSL, an updater or a service.

The requested offline /etc/pip.conf fixture cannot admit the reviewed helper if
pip suppresses all configuration. A fresh native --copies venv demonstrates that
behavior without writing host pip configuration or downloading dependencies.
This is not installed Linux runtime acceptance, nor permission to fix production.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.probe_harness_adoption import SOURCE_HEAD

ROOT = Path(__file__).resolve().parents[1]
HELPER = "installer/update_prepare.py"
HELPER_SHA256 = "260b76e82ca6ab712a84362a0f022d783db62f6e2b114fe442da8a2229a3106f"


def reviewed_helper():
    """Read the exact reviewed Git object, never the current harness worktree."""
    raw = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{SOURCE_HEAD}:{HELPER}"],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    if hashlib.sha256(raw).hexdigest() != HELPER_SHA256:
        raise ValueError("Exact reviewed production helper required")
    return raw


def dependency_environment(raw):
    """Extract literal dependency env without importing/executing candidate code."""
    tree = ast.parse(raw)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_dependencies"
    )
    environments = [
        ast.literal_eval(node.value)
        for node in function.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "env" for target in node.targets)
    ]
    if len(environments) != 1 or type(environments[0]) is not dict:
        raise ValueError("Unknown reviewed dependency environment")
    return environments[0]


def probe_pip_configuration(directory):
    """Real pip, no network: positive config control followed by null-file case.

    Native Windows uses pip.ini/nul; Linux uses pip.conf//dev/null. This portable
    experiment proves pip's null-device semantics, not guest installation state.
    No monkeypatch, downloader/manager adapter or pip environment shortcut is used.
    """
    venv = Path(directory) / "venv"
    # Refuse reuse, including dangling links; no generic cleanup/adoption path.
    if os.path.lexists(venv):
        raise ValueError("Fresh diagnostic venv required")
    subprocess.run(
        [sys.executable, "-I", "-m", "venv", "--copies", str(venv)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    config = venv / ("pip.ini" if os.name == "nt" else "pip.conf")
    with config.open("x", encoding="ascii") as stream:
        stream.write("[global]\nno-index = true\n")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    argv = [str(python), "-I", "-m", "pip", "--isolated", "config", "get", "global.no-index"]
    control = subprocess.run(argv, env=env, capture_output=True, timeout=30)
    suppressed = subprocess.run(
        argv, env={**env, "PIP_CONFIG_FILE": os.devnull}, capture_output=True, timeout=30
    )
    if control.returncode != 0 or control.stdout.strip() != b"true":
        raise ValueError("Positive pip configuration control did not load")
    if suppressed.returncode != 1 or b"No such key" not in suppressed.stderr:
        raise ValueError("Unexpected pip null-configuration behavior; retain evidence")
    return {
        "positive_control_loaded": True,
        "null_device_suppressed_configuration": True,
        "positive_control_exit": control.returncode,
        "null_device_exit": suppressed.returncode,
        "platform": sys.platform,
    }


def admission(raw, observation):
    env = dependency_environment(raw)
    if env.get("PIP_CONFIG_FILE") != "/dev/null":
        raise ValueError("Reviewed helper changed; this diagnostic is not an approval")
    if not (
        observation["positive_control_loaded"]
        and observation["null_device_suppressed_configuration"]
    ):
        raise ValueError("Missing real pip evidence")
    return {
        "admitted": False,
        "reason": "PIP_CONFIG_FILE=/dev/null suppresses /etc/pip.conf offline wheelhouse settings",
        "production_head": SOURCE_HEAD,
        "helper_sha256": hashlib.sha256(raw).hexdigest(),
        "pip": observation,
        "actual_guest_update_verified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)  # No phase/destination/transport overrides accepted.
    raw = reviewed_helper()
    with tempfile.TemporaryDirectory(prefix="knxoh-offline-admission-") as temporary:
        result = admission(raw, probe_pip_configuration(temporary))
    print(json.dumps(result, indent=2))
    return 2  # A blocked admission must never look like successful acceptance.


if __name__ == "__main__":
    raise SystemExit(main())
