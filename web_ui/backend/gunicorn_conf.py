from web_ui.backend.storage import load_config

conf = load_config()

# Default settings
bind_host = conf.get("bind_host", "0.0.0.0")
port = conf.get("port", 8085)

# Gunicorn settings
bind = f"{bind_host}:{port}"
workers = 1
accesslog = "-"
errorlog = "-"
# Reload on code changes if needed (optional)
# reload = False
