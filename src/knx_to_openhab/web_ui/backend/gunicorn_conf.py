import json
import os
import multiprocessing

# Locate config.json relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

conf = load_config()

# Default settings
bind_host = conf.get('bind_host', '0.0.0.0')
port = conf.get('port', 8085)

# Gunicorn settings
bind = f"{bind_host}:{port}"
workers = 1
accesslog = '-'
errorlog = '-'
# Reload on code changes if needed (optional)
# reload = False
