"""Windows controller for the already deployed, approved own-nspawn fixture.

Requires the reviewed d1f1848 harness and private root receipt already installed
inside the inner guest. It never deploys/changes the provider or existing source.
Bootstrap is fresh-only and intentionally refuses partial fixtures; no cleanup,
policy override or resume-by-guessing is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READINESS_RUNNER_FILES = (
    "scripts/run_nested_systemd_acceptance.py",
    "scripts/nested_fixture_repair.py",
    "scripts/nested_systemd_fixture.py",
    "scripts/nested_fixture_state.py",
    "scripts/nested_acceptance.py",
)
REPAIR_EVIDENCE_FILES = ("repair-environmentfile.log", "installed-green.log", "diagnostic.log")
sys.path.insert(0, str(ROOT))
from scripts import nested_acceptance as provider  # noqa: E402


def read_pinned_json(path, digest):
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Explicit out-of-guest manifest pin required")
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Manifest pin/size mismatch")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate manifest field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Invalid manifest number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def verify_readiness_inputs(approval):
    """Controller-approved existing receipts, not an observation/enrollment API."""
    if type(approval) is not dict or set(approval) != {"state", "runner_files", "evidence_files"}:
        raise ValueError("Explicit readiness runner/evidence pins required")
    runners, evidence = approval["runner_files"], approval["evidence_files"]
    if (
        type(runners) is not dict
        or set(runners) != set(READINESS_RUNNER_FILES)
        or type(evidence) is not dict
        or len(evidence) != len(REPAIR_EVIDENCE_FILES)
        or {Path(p).name for p in evidence} != set(REPAIR_EVIDENCE_FILES)
    ):
        raise ValueError("Incomplete readiness runner/evidence pins")
    for path, digest in [(ROOT / p, h) for p, h in runners.items()] + [
        (Path(p), h) for p, h in evidence.items()
    ]:
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Readiness runner/evidence pin mismatch")


def guest_program(
    phase,
    nonce,
    *,
    checkpoint=None,
    source_approval=None,
    approved_head=None,
    readiness_approval=None,
):
    if phase == "repair-environmentfile":
        raise ValueError("Installed repair checkpoint consumed; repair cannot be repeated")
    if phase not in (
        "bootstrap",
        "probe",
        "sudo-regression",
        "checkpoint-inventory",
        "resume-after-sudo",
        "readiness-only",
    ):
        raise ValueError("Unsupported own-nested acceptance phase")
    if phase == "readiness-only":
        from scripts.nested_fixture_repair import (
            validate_readiness_approval,
            validate_repair_source,
        )

        if checkpoint is None or source_approval is None or approved_head is None:
            raise ValueError("readiness-only requires pinned historical checkpoint and source")
        validate_readiness_approval(checkpoint, readiness_approval, nonce, approved_head)
        validate_repair_source(source_approval, approved_head, checkpoint["old_source_approval"])
    elif phase == "resume-after-sudo":
        from scripts.nested_fixture_state import validate_checkpoint, validate_source_manifest

        if checkpoint is None or source_approval is None or approved_head is None:
            raise ValueError("Resume requires pinned checkpoint AND reviewed source approval")
        validate_checkpoint(checkpoint, checkpoint["inventory"], nonce)
        validate_source_manifest(source_approval, approved_head)
    elif phase == "probe" and (source_approval is not None or approved_head is not None):
        from scripts.nested_fixture_state import validate_source_manifest

        validate_source_manifest(source_approval, approved_head)
    fixture = (ROOT / "scripts/nested_systemd_fixture.py").read_text(encoding="utf-8")
    state = (ROOT / "scripts/nested_fixture_state.py").read_text(encoding="utf-8")
    code = (
        "import sys,os,json,hashlib,types\nfrom pathlib import Path\n"
        "sys.dont_write_bytecode=True\n"
        "sys.path.insert(0,'/opt/knxoh-harness-d1f1848')\n"
        "module=types.ModuleType('scripts.nested_fixture_state')\n"
        "sys.modules[module.__name__]=module\n"
        f"exec(compile({state!r},'<trusted fixture state>','exec'),module.__dict__)\n"
        f"exec(compile({fixture!r},'<trusted acceptance fixture>','exec'))\n"
        f"EXPECTED_NONCE={nonce!r}\nrequire_guest(EXPECTED_NONCE)\n"
    )
    if phase == "readiness-only":
        repair = (ROOT / "scripts/nested_fixture_repair.py").read_text(encoding="utf-8")
        return (
            code
            + "module=types.ModuleType('scripts.nested_fixture_repair')\n"
            + "sys.modules[module.__name__]=module\n"
            + f"exec(compile({repair!r},'<trusted repair boundary>','exec'),module.__dict__)\n"
            + f"run_phase('readiness-only',EXPECTED_NONCE,checkpoint={checkpoint!r},"
            + f"source_approval={source_approval!r},approved_head={approved_head!r},"
            + f"readiness_approval={readiness_approval!r})\n"
        )
    if phase == "checkpoint-inventory":
        return (
            code
            + "from scripts.nested_fixture_state import checkpoint_candidate\nprint(json.dumps(checkpoint_candidate(collect_inventory(details=True),EXPECTED_NONCE)))\n"
        )
    if phase == "resume-after-sudo":
        return (
            code
            + f"resume_after_sudo(EXPECTED_NONCE,{checkpoint!r},{source_approval!r},{approved_head!r})\n"
        )
    if phase == "probe" and source_approval is not None:
        return (
            code
            + f"probe(EXPECTED_NONCE,source_approval={source_approval!r},approved_head={approved_head!r})\n"
        )
    if phase != "sudo-regression":
        return code + f"run_phase({phase!r},EXPECTED_NONCE)\n"
    raw = (ROOT / "tests/integration/test_update_sudo_runtime.py").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    code += f"""
root=Path('/root/knxoh-acceptance-tests')/{digest[:12]!r}
root.mkdir(mode=0o700,parents=True,exist_ok=True)
target=root/'test_update_sudo_runtime.py'
raw={raw!r}
if target.exists():
    assert not target.is_symlink() and target.stat().st_uid==0
    assert hashlib.sha256(target.read_bytes()).hexdigest()=={digest!r}
else:
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:
        stream.write(raw)
os.environ['KNXOH_DISPOSABLE_SYSTEMD_NONCE']=EXPECTED_NONCE
os.environ['KNXOH_LIVE_SUDO_ACCEPTANCE']='own-nested-read-only'
import pytest
raise SystemExit(pytest.main(['-q','-s',str(target),'-o','addopts=','--tb=short','-p','no:cacheprovider']))
"""
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument(
        "--phase",
        required=True,
        choices=(
            "bootstrap",
            "probe",
            "sudo-regression",
            "checkpoint-inventory",
            "resume-after-sudo",
            "repair-environmentfile",
            "readiness-only",
        ),
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--source-approval", type=Path)
    parser.add_argument("--source-approval-sha256")
    parser.add_argument("--approved-source-head")
    parser.add_argument("--readiness-approval", type=Path)
    parser.add_argument("--readiness-approval-sha256")
    args = parser.parse_args()
    if args.phase == "repair-environmentfile":
        parser.error("Installed repair checkpoint consumed; repair cannot be repeated")
    if args.phase != "readiness-only" and (
        args.readiness_approval or args.readiness_approval_sha256
    ):
        parser.error("readiness approval is valid ONLY for readiness-only")
    receipt = provider.decode_receipt(args.receipt.read_text(encoding="utf-8"))
    provider.validate_receipt(receipt)
    resume = {}
    supplied = (
        args.checkpoint,
        args.checkpoint_sha256,
        args.source_approval,
        args.source_approval_sha256,
        args.approved_source_head,
    )
    if args.phase in ("resume-after-sudo", "readiness-only"):
        if not all(supplied):
            parser.error(
                "continuation requires checkpoint/source files, both SHA-256 pins and approved commit"
            )
        resume = dict(
            checkpoint=read_pinned_json(args.checkpoint, args.checkpoint_sha256),
            source_approval=read_pinned_json(args.source_approval, args.source_approval_sha256),
            approved_head=args.approved_source_head,
        )
        if args.phase == "readiness-only":
            if not args.readiness_approval or not args.readiness_approval_sha256:
                parser.error("readiness-only requires separately pinned readiness approval")
            approval = read_pinned_json(args.readiness_approval, args.readiness_approval_sha256)
            verify_readiness_inputs(approval)
            resume["readiness_approval"] = approval["state"]
    elif args.phase == "probe" and any(supplied):
        if args.checkpoint or args.checkpoint_sha256 or not all(supplied[2:]):
            parser.error(
                "probe source selection requires only source approval, its pin, and approved commit"
            )
        resume = dict(
            source_approval=read_pinned_json(args.source_approval, args.source_approval_sha256),
            approved_head=args.approved_source_head,
        )
    elif any(supplied):
        parser.error("continuation approval arguments are valid ONLY for resume-after-sudo")
    program = guest_program(args.phase, receipt["nonce"], **resume)
    provider.validate_registration(provider.registration())
    observations = provider.preflight(receipt)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    (args.evidence_dir / (args.phase + "-preflight.json")).write_text(
        json.dumps(observations, indent=2), encoding="utf-8"
    )
    result = subprocess.run(
        [
            "wsl.exe",
            "-d",
            provider.DISTRIBUTION,
            "--",
            "/usr/bin/systemd-run",
            "--machine=" + provider.MACHINE,
            "--wait",
            "--pipe",
            "--collect",
            "/opt/knxoh-test-venv/bin/python",
            "-B",
            "-",
        ],
        input=program,
        text=True,
        capture_output=True,
        timeout=1800,
    )
    (args.evidence_dir / (args.phase + ".log")).write_text(
        result.stdout + "\nSTDERR\n" + result.stderr, encoding="utf-8"
    )
    if args.phase == "checkpoint-inventory" and result.returncode == 0:
        # Candidate contains a private nonce. Save privately, never echo it.
        candidate = json.loads(result.stdout)
        from scripts.nested_fixture_state import validate_checkpoint

        validate_checkpoint(candidate, candidate["inventory"], receipt["nonce"])
        path = args.evidence_dir / "checkpoint-candidate.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(candidate, stream, indent=2)
        print("Read-only checkpoint candidate saved; requires controller SHA-256 pin:", path)
    else:
        print(result.stdout)
    print(result.stderr, file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
