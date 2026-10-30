"""Real loopback TLS, temporary CA only; no DNS or system trust changes."""

import hashlib
import http.client
import shutil
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from tests.test_release_fixture_data import wheel


def server_api():
    from scripts import release_fixture_server

    return release_fixture_server


@pytest.fixture
def tls(tmp_path):
    openssl = shutil.which("openssl") or "C:/Program Files/Git/usr/bin/openssl.exe"
    if not Path(openssl).is_file():
        pytest.skip("openssl executable unavailable")
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=pypi.org",
            "-addext",
            "subjectAltName=DNS:pypi.org,DNS:files.pythonhosted.org",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    from scripts.release_fixture_data import index_routes, inspect_wheel

    item = inspect_wheel(*wheel())
    server = server_api().make_server(index_routes([item]), cert, key, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, cert, item
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def request(server, cert, method, host, path, *, tls_host="pypi.org", trust=True, headers=()):
    context = (
        ssl.create_default_context(cafile=str(cert)) if trust else ssl.create_default_context()
    )
    import socket

    with socket.create_connection(server.server_address, timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=tls_host) as connection:
            message = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
            message += "".join(f"{key}: {value}\r\n" for key, value in headers) + "\r\n"
            connection.sendall(message.encode("ascii"))
            response = http.client.HTTPResponse(connection, method=method)
            response.begin()
            return response.status, dict(response.getheaders()), response.read()


def test_real_tls_html_fallback_and_complete_wheel(tls):
    server, cert, item = tls
    status, headers, body = request(
        server,
        cert,
        "GET",
        "pypi.org",
        "/simple/flask/",
        headers=[("Accept", "application/vnd.pypi.simple.v1+json, text/html")],
    )
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert str(item.sha256).encode() in body and len(body) == int(headers["Content-Length"])
    status, headers, body = request(
        server, cert, "GET", "files.pythonhosted.org", item.path, tls_host="files.pythonhosted.org"
    )
    assert status == 200 and body == item.body
    assert hashlib.sha256(body).hexdigest() == item.sha256
    assert len(body) == int(headers["Content-Length"])
    status, head_headers, body = request(server, cert, "HEAD", "files.pythonhosted.org", item.path)
    assert status == 200 and not body
    assert head_headers["Content-Length"] == headers["Content-Length"]


@pytest.mark.parametrize(
    "method,host,path,extra",
    [
        ("POST", "pypi.org", "/simple/", ()),
        ("GET", "evil.org", "/simple/", ()),
        ("GET", "pypi.org:443", "/simple/", ()),
        ("GET", "PyPI.org", "/simple/", ()),
        ("GET", "pypi.org", "/simple/Flask/", ()),
        ("GET", "pypi.org", "/simple/flask/?phase=retry", ()),
        ("GET", "pypi.org", "/simple/../etc/passwd", ()),
        ("GET", "pypi.org", "/simple/%2e%2e/", ()),
        ("GET", "pypi.org", "https://pypi.org/simple/", ()),
        ("GET", "pypi.org", "//simple/", ()),
        ("GET", "pypi.org", "/simple/", (("Host", "files.pythonhosted.org"),)),
        ("GET", "pypi.org", "/simple/", (("Transfer-Encoding", "chunked"),)),
        ("GET", "pypi.org", "/simple/", (("Content-Length", "1"),)),
    ],
)
def test_exact_allowlist(tls, method, host, path, extra):
    server, cert, _ = tls
    assert request(server, cert, method, host, path, headers=extra)[0] in (400, 404, 405)


def test_real_hostname_and_chain_rejection(tls):
    server, cert, _ = tls
    with pytest.raises(ssl.SSLCertVerificationError):
        request(server, cert, "GET", "pypi.org", "/simple/", tls_host="wrong.example")
    with pytest.raises(ssl.SSLCertVerificationError):
        request(server, cert, "GET", "pypi.org", "/simple/", trust=False)


def test_only_loopback_listener():
    with pytest.raises(ValueError):
        server_api().make_server({}, "not-read", "not-read", address="0.0.0.0")


def test_all_real_exported_wheels_over_verified_tls(tls):
    directory = Path(__file__).resolve().parents[1] / "wsl-acceptance/wheels-02"
    if not directory.exists():
        pytest.skip("Private read-only 29-wheel snapshot unavailable; no download fallback")
    from scripts.release_fixture_data import index_routes, inventory_wheels

    wheels = inventory_wheels(directory)
    assert len(wheels) == 29 and sum(len(w.body) for w in wheels) == 6967956
    server, cert, _ = tls
    # A second listener uses the same temporary-only certificate.
    other = server_api().make_server(index_routes(wheels), cert, cert.parent / "key.pem", port=0)
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    try:
        for item in wheels:
            status, headers, body = request(
                other,
                cert,
                "GET",
                "files.pythonhosted.org",
                item.path,
                tls_host="files.pythonhosted.org",
            )
            assert status == 200 and body == item.body
            assert int(headers["Content-Length"]) == len(body)
            assert hashlib.sha256(body).hexdigest() == item.sha256
    finally:
        other.shutdown()
        thread.join(timeout=5)
        other.server_close()
