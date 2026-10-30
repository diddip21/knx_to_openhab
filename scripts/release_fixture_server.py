"""Fixed loopback TLS fixture, exact immutable Host/path allowlists; no proxy.

Standalone service entry point has no destination, phase or bind-address options.
The operator alone writes the private root control file. No application import.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType

CONTROL_ROOT = Path("/root/knxoh-release-fixture")
HOSTS = (
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
)


def make_server(
    routes, certificate, key, *, address="127.0.0.1", port=443, select=None, audit=None
):
    """Portable TLS listener; caller owns its lifecycle and temporary trust files."""
    if address != "127.0.0.1":
        raise ValueError("Only IPv4 loopback is permitted")
    fixed = MappingProxyType(dict(routes))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Never log arbitrary client values or cookie/auth headers.

        def respond(self):
            self.close_connection = True
            # BaseHTTPRequestHandler canonicalizes a leading // before dispatch.
            # Match the raw target as well; aliases must never enter our allowlist.
            fields = self.raw_requestline.split()
            if len(fields) != 3 or fields[1] != self.path.encode("iso-8859-1"):
                self.send_error(400)
                return
            hosts = self.headers.get_all("Host", [])
            lengths = self.headers.get_all("Content-Length", [])
            if (
                len(hosts) != 1
                or self.headers.get_all("Transfer-Encoding")
                or lengths not in ([], ["0"])
            ):
                self.send_error(400)
                return
            if self.command not in ("GET", "HEAD"):
                self.send_error(405)
                return
            allowed = fixed if select is None else select()
            value = allowed.get((hosts[0], self.path))
            if value is None:
                self.send_error(404)
                return
            content_type, body = value
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)
            if audit is not None:
                audit(self.command, hosts[0], self.path, len(body))

        do_GET = respond
        do_HEAD = respond
        do_POST = respond
        do_PUT = respond
        do_DELETE = respond
        do_OPTIONS = respond
        do_PATCH = respond

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(key))
    server = ThreadingHTTPServer((address, port), Handler)
    server.daemon_threads = True
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main():
    if len(sys.argv) != 1 or os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Fixed inner-root service entry only")
    if Path(__file__).resolve().parent != CONTROL_ROOT:
        raise ValueError("Fixed trusted server origin required")
    sys.path.insert(0, str(CONTROL_ROOT))
    from release_fixture_data import (
        PHASES,
        index_routes,
        inventory_wheels,
        read_regular,
        release_routes,
    )

    manifest = json.loads(read_regular(CONTROL_ROOT / "artifacts/manifest.json", owner=0))
    wheels = inventory_wheels(CONTROL_ROOT / "wheels", owner=0)
    if len(wheels) != 29:
        raise ValueError("Complete admitted wheelhouse required")
    index = index_routes(wheels)
    selections = {
        phase: MappingProxyType(
            {**index, **release_routes(CONTROL_ROOT / "artifacts", manifest, phase)}
        )
        for phase in PHASES
    }

    def select():
        phase = read_regular(CONTROL_ROOT / "phase", 64, owner=0).decode().strip()
        return selections[phase]

    def audit(method, host, path, size):
        print(json.dumps(dict(method=method, host=host, path=path, size=size)), flush=True)

    with make_server(
        {}, CONTROL_ROOT / "server.crt", CONTROL_ROOT / "server.key", select=select, audit=audit
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
