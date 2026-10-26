import json

import pytest

from installer.web_ui_endpoint import resolve_web_ui_endpoint


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"bind_host": "127.0.0.1", "port": 8085}), encoding="utf-8")
    return path


def _set_config(path, bind_host, port=8085):
    path.write_text(json.dumps({"bind_host": bind_host, "port": port}), encoding="utf-8")


@pytest.mark.parametrize(
    ("bind_host", "expected_host"),
    [("127.0.0.1", "127.0.0.1"), ("::1", "[::1]"), ("localhost", "localhost")],
)
def test_loopback_endpoint_preserves_reachable_host_and_configured_port(
    config_path, bind_host, expected_host
):
    _set_config(config_path, bind_host, 9090)

    assert resolve_web_ui_endpoint(config_path, "192.168.1.10") == (
        "loopback",
        expected_host,
        9090,
    )


@pytest.mark.parametrize(
    ("bind_host", "expected_host"),
    [("0.0.0.0", "192.168.1.10"), ("::", "[2001:db8::10]")],
)
def test_wildcard_endpoint_uses_matching_detected_lan_ip(config_path, bind_host, expected_host):
    _set_config(config_path, bind_host)

    assert resolve_web_ui_endpoint(config_path, "192.168.1.10 2001:db8::10") == (
        "network",
        expected_host,
        8085,
    )


def test_specific_bind_endpoint_uses_configured_address(config_path):
    _set_config(config_path, "192.168.1.50")

    assert resolve_web_ui_endpoint(config_path, "192.168.1.10") == (
        "network",
        "192.168.1.50",
        8085,
    )


def test_ipv6_endpoint_is_bracketed_for_url(config_path):
    _set_config(config_path, "2001:db8::10")

    assert resolve_web_ui_endpoint(config_path, "192.168.1.10") == (
        "network",
        "[2001:db8::10]",
        8085,
    )


def test_unavailable_wildcard_address_uses_placeholder(config_path):
    _set_config(config_path, "0.0.0.0")

    assert resolve_web_ui_endpoint(config_path, "") == ("network", "<device-ip>", 8085)


def test_wildcard_endpoint_skips_wrong_family_and_loopback_addresses(config_path):
    _set_config(config_path, "::")

    assert resolve_web_ui_endpoint(config_path, "127.0.0.1 fe80::1") == (
        "network",
        "<device-ip>",
        8085,
    )


def test_invalid_port_is_rejected(config_path):
    _set_config(config_path, "127.0.0.1", 70000)

    with pytest.raises(ValueError, match="between 1 and 65535"):
        resolve_web_ui_endpoint(config_path, "192.168.1.10")
