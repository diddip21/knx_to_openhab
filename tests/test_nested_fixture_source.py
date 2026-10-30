"""Approval parsing tests: synthetic manifests/read-only files, no WSL calls."""

import hashlib
import json

import pytest

from scripts import nested_fixture_state as state
from scripts import run_nested_systemd_acceptance as runner

HEAD = "de" * 20


@pytest.fixture
def approval():
    files = {
        name: {"sha256": "ab" * 32, "mode": 0o644}
        for name in (
            "installer/update_bootstrap.py",
            "installer/bootstrap_activation.py",
            "installer/update_core/__init__.py",
            "requirements.txt",
            "VERSION",
        )
    }
    files["requirements.txt"][
        "sha256"
    ] = "836f5d08439f7a536cae171993c199821a95d1face231826a49bb0043a5829fe"
    return dict(
        format=1,
        purpose="reviewed-sudo-fix-source",
        head=HEAD,
        production_base="27d106a26c907b7ce05d1880ea25157b1f815e50",
        review_approved=True,
        root="/opt/knxoh-source-" + HEAD,
        archive_sha256="cd" * 32,
        files=files,
    )


def test_explicit_full_new_source_identity(approval):
    assert state.validate_source_manifest(approval, HEAD).as_posix() == approval["root"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("format", True),
        ("review_approved", False),
        ("review_approved", 1),
        ("head", "ef" * 20),
        ("root", "/opt/other"),
        ("production_base", "ef" * 20),
        ("archive_sha256", None),
        ("archive_sha256", "bad"),
        ("purpose", "unreviewed"),
    ],
)
def test_unapproved_or_mismatched_source_is_refused(approval, field, value):
    approval[field] = value
    with pytest.raises(ValueError):
        state.validate_source_manifest(approval, HEAD)


@pytest.mark.parametrize(
    "name,value",
    [
        ("venv/bin/python", {"sha256": "ab" * 32, "mode": 0o755}),
        ("../outside.py", {"sha256": "ab" * 32, "mode": 0o644}),
        ("/outside.py", {"sha256": "ab" * 32, "mode": 0o644}),
        ("unknown.py", {"sha256": None, "mode": 0o644}),
        ("unknown.py", {"sha256": "ab" * 32, "mode": 0o666}),
        ("requirements.txt", {"sha256": "ab" * 32, "mode": 0o644}),
    ],
)
def test_bad_file_map_is_not_a_source_approval(approval, name, value):
    approval["files"][name] = value
    with pytest.raises(ValueError):
        state.validate_source_manifest(approval, HEAD)


def test_operator_manifest_pin_is_checked_before_parsing(tmp_path):
    path = tmp_path / "approval.json"
    path.write_bytes(b"not json")
    with pytest.raises(ValueError, match="pin"):
        runner.read_pinned_json(path, "00" * 32)


def test_operator_manifest_pin_rejects_duplicates(tmp_path):
    path = tmp_path / "approval.json"
    raw = b'{"format":1,"format":2}'
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="Duplicate"):
        runner.read_pinned_json(path, hashlib.sha256(raw).hexdigest())


def test_operator_manifest_pin_accepts_exact_bytes(tmp_path, approval):
    path = tmp_path / "approval.json"
    raw = json.dumps(approval).encode()
    path.write_bytes(raw)
    assert runner.read_pinned_json(path, hashlib.sha256(raw).hexdigest()) == approval


def test_resume_is_not_available_without_both_explicit_approvals():
    with pytest.raises(ValueError):
        runner.guest_program("resume-after-sudo", "ab" * 32)
