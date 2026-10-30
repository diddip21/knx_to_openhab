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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import nested_acceptance as provider  # noqa: E402


def guest_program(phase, nonce):
    if phase not in ("bootstrap", "probe", "sudo-regression"):
        raise ValueError("Unsupported own-nested acceptance phase")
    fixture = (ROOT / "scripts/nested_systemd_fixture.py").read_text(encoding="utf-8")
    code = (
        "import sys,os,json,hashlib\nfrom pathlib import Path\n"
        "sys.dont_write_bytecode=True\n"
        f"exec(compile({fixture!r},'<trusted acceptance fixture>','exec'))\n"
        f"EXPECTED_NONCE={nonce!r}\nrequire_guest(EXPECTED_NONCE)\n"
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
    parser.add_argument("--phase", required=True, choices=("bootstrap", "probe", "sudo-regression"))
    args = parser.parse_args()
    receipt = provider.decode_receipt(args.receipt.read_text(encoding="utf-8"))
    provider.validate_receipt(receipt)
    provider.validate_registration(provider.registration())
    observations = provider.preflight(receipt)
    program = guest_program(args.phase, receipt["nonce"])
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
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
