"""Backend package for the web UI.

This package contains the Flask application and supporting modules for the
web-based KNX to OpenHAB converter.
"""

# Import and expose the Flask app for use by deployment tools
try:
    from .app import app
    __all__ = ['app']
except ImportError:
    # Flask may not be installed in all environments
    __all__ = []
