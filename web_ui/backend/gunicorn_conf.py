from installer.update_submit import SUBMISSION_WAIT_SECONDS
from web_ui.backend.storage import load_config

conf = load_config()

# Default settings
bind_host = conf.get("bind_host", "127.0.0.1")
port = conf.get("port", 8085)

# Gunicorn settings
bind = f"{bind_host}:{port}"
workers = 1
# Keep process-local jobs in one worker, but leave threads available for status,
# login and other UI requests while a submission waits for its protected claim.
worker_class = "gthread"
threads = 4
# 3 * 5 seconds for manager calls + 30 for ack, with 15 seconds of I/O/scheduling
# headroom. Do not rely on Gunicorn's default 30-second sync-worker timeout.
timeout = int(SUBMISSION_WAIT_SECONDS) + 15
graceful_timeout = timeout
accesslog = "-"
errorlog = "-"
# Reload on code changes if needed (optional)
# reload = False
