"""Entry point for running the web UI backend as a module.

Usage: python -m web_ui.backend
"""
from .app import app, cfg, FLASK_AVAILABLE

if __name__ == "__main__":
    if not FLASK_AVAILABLE:
        print("Flask is not installed. Please install requirements to run the server.")
        exit(1)

    host = cfg.get("bind_host", "0.0.0.0")
    port = cfg.get("port", 8080)
    print(f"Starting Flask server on {host}:{port}...")
    app.run(host=host, port=port, debug=False)
