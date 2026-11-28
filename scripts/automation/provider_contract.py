"""Verify the pinned CLI's actual free-price request body against a local server."""

import json
import queue
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.free_providers import OPENROUTER_MODELS, guard_config  # noqa: E402
from opencode_model_router import isolated_environment  # noqa: E402


def main() -> int:
    requests: queue.Queue = queue.Queue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.put(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = b'{"error":{"message":"local contract stop","code":400}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = guard_config()
            config["providers"]["openrouter"]["settings"] = {
                "baseURL": f"http://127.0.0.1:{server.server_port}/v1"
            }
            environment = isolated_environment()
            environment.update(
                OPENROUTER_API_KEY="local-fake-key", OPENCODE_CONFIG_CONTENT=json.dumps(config)
            )
            with tempfile.TemporaryDirectory() as cwd:
                environment["PWD"] = cwd
                environment["XDG_DATA_HOME"] = str(Path(cwd) / "data")
                subprocess.run(
                    [
                        "opencode",
                        "run",
                        "--standalone",
                        "--archived",
                        "--format",
                        "json",
                        "--model",
                        OPENROUTER_MODELS[0],
                        "Read-only request contract check.",
                    ],
                    cwd=cwd,
                    env=environment,
                    capture_output=True,
                    timeout=45,
                    check=False,
                )
            body = requests.get(timeout=1)
            expected = guard_config()["providers"]["openrouter"]["models"][
                OPENROUTER_MODELS[0].split("/", 1)[1]
            ]["body"]
            assert body["model"] == OPENROUTER_MODELS[0].split("/", 1)[1]
            assert body["provider"] == expected["provider"]
            assert body["models"] == expected["models"]
            assert body["plugins"] == []
        except Exception:
            print("::error::free_provider_request_contract_failed")
            return 1
        finally:
            server.shutdown()
    print("free_provider_request_contract_passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
