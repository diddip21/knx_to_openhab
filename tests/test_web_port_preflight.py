import json
import socket
from io import StringIO
from pathlib import Path

import pytest

from installer.check_web_port import check_web_port
from installer.configure_bind import configure_bind

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


def test_port_checker_accepts_config_from_stdin(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    monkeypatch.setattr(
        "sys.stdin",
        StringIO(json.dumps({"bind_host": "127.0.0.1", "port": port})),
    )

    assert check_web_port(None) == ("127.0.0.1", port)


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


def test_recently_closed_server_connection_allows_port_reuse(tmp_path):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        host, port = listener.getsockname()
        with socket.socket() as client:
            client.connect((host, port))
            server_connection, _ = listener.accept()
            server_connection.close()
            assert client.recv(1) == b""

    assert check_web_port(_config(tmp_path, host, port)) == (host, port)


def test_decimal_string_port_remains_supported(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    assert check_web_port(_config(tmp_path, "127.0.0.1", str(port))) == ("127.0.0.1", port)


def test_selected_external_bind_does_not_require_loopback_port_free(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        getaddrinfo = socket.getaddrinfo

        def resolve_bind_host(host, requested_port, **kwargs):
            if host == "lan-test":
                return getaddrinfo("127.0.0.2", requested_port, **kwargs)
            return getaddrinfo(host, requested_port, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", resolve_bind_host)
        assert check_web_port(_config(tmp_path, "lan-test", port)) == ("lan-test", port)


def test_hostname_probe_matches_gunicorn_ipv4_selection(tmp_path, monkeypatch):
    if not socket.has_ipv6:
        pytest.skip("the host does not support IPv6")

    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as listener:
        try:
            listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            listener.bind(("::1", 0))
        except OSError as error:
            pytest.skip(f"IPv6 loopback is unavailable: {error}")
        listener.listen()
        port = listener.getsockname()[1]
        getaddrinfo = socket.getaddrinfo
        families = []

        def resolve_ipv4_endpoint(host, requested_port, *, family, **kwargs):
            families.append(family)
            return getaddrinfo(host, requested_port, family=family, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", resolve_ipv4_endpoint)
        assert check_web_port(_config(tmp_path, "localhost", port)) == ("localhost", port)
        assert families == [socket.AF_INET]


def test_loopback_fallback_is_checked_after_bind_selection(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        config = _config(tmp_path, "192.168.1.10", port)

        assert configure_bind(config, confirm_external=lambda _host: False)
        with pytest.raises(OSError):
            check_web_port(config)


def test_ipv6_wildcard_probe_preserves_dual_stack_behavior(tmp_path):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
        if probe.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY):
            pytest.skip("the host configures IPv6 wildcard sockets as IPv6-only")

    with socket.socket(socket.AF_INET) as listener:
        listener.bind(("0.0.0.0", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            check_web_port(_config(tmp_path, "::", port))


@pytest.mark.parametrize("port", [0, 65536, "not-a-port", True])
def test_invalid_web_port_is_rejected(tmp_path, port):
    with pytest.raises(ValueError, match="port"):
        check_web_port(_config(tmp_path, "127.0.0.1", port))


def test_setup_checks_port_after_quiescing_and_before_migration():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")
    quiesce = setup.index("acquire_setup_maintenance_lock quiesce_setup_services")
    bind_selection = setup.index('"$AUTH_PREFLIGHT_CONFIG" --output "$BIND_PREFLIGHT_CONFIG"')
    port_check = setup.index(
        'sudo -u "$SERVICE_USER" python3 "$REPO_ROOT/installer/check_web_port.py" -'
    )
    bind_publish = setup.index('sudo mv -f -- "$BIND_PREFLIGHT_CONFIG" "$AUTH_PREFLIGHT_CONFIG"')
    migration = setup.index("migrate_runtime_data.py")

    assert quiesce < bind_selection < port_check < bind_publish < migration
