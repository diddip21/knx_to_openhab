import json
import socket
from pathlib import Path

import pytest

from installer.check_web_port import check_web_port

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path, host, port):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"bind_host": host, "port": port}), encoding="utf-8")
    return path


def test_free_web_port_is_accepted(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    assert check_web_port(_config(tmp_path, "127.0.0.1", port)) == ("127.0.0.1", port)


def test_occupied_web_port_is_rejected(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            check_web_port(_config(tmp_path, "127.0.0.1", port))


def test_wildcard_bind_detects_a_loopback_listener(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            check_web_port(_config(tmp_path, "0.0.0.0", port))


@pytest.mark.parametrize("port", [0, 65536, "8085", True])
def test_invalid_web_port_is_rejected(tmp_path, port):
    with pytest.raises(ValueError, match="port"):
        check_web_port(_config(tmp_path, "127.0.0.1", port))


def test_setup_checks_port_after_quiescing_and_before_migration():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    quiesce = setup.index("acquire_setup_maintenance_lock quiesce_setup_services")
    port_check = setup.index('python3 "$REPO_ROOT/installer/check_web_port.py"')
    migration = setup.index("migrate_runtime_data.py")

    assert quiesce < port_check < migration
