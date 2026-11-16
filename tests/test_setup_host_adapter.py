"""Regression coverage for the isolated setup host adapter's pipe contract."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_port_check_adapter_consumes_piped_configuration(tmp_path):
    checker = tmp_path / "knxoh-check-web-port.test"
    checker.touch()
    # More than a pipe buffer makes an early reader exit fail deterministically.
    payload = b'{"padding":"' + b"x" * 2_000_000 + b'"}'
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/fixtures/setup_host.py"), "python3", str(checker), "-"],
        env=os.environ | {"SETUP_SANDBOX": str(tmp_path)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        process.stdin.write(payload)
        process.stdin.close()
        assert process.wait(timeout=15) == 0
        assert process.stderr is not None
        assert process.stderr.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=15)
        process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
