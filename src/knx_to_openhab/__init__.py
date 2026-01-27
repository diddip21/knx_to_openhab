"""KNX to OpenHAB - Convert KNX projects to OpenHAB configuration.

This package converts KNX project files (ETS) to OpenHAB configuration files
(items, things, sitemaps, rules, persistence).

Main entry points:
  - CLI: knx-to-openhab <knx-file>
  - Web UI: knx-to-openhab web
  - Python API: from knx_to_openhab import knxproject
"""

__version__ = "1.0.0"
__author__ = "Patrick G"
__license__ = "MIT"

# Lazy loading - only import when explicitly requested
# This allows the package to be imported without side effects

def __getattr__(name):
    """Lazy import of submodules."""
    if name == 'generator':
        from . import generator
        return generator
    elif name == 'knxproject':
        from . import knxproject
        return knxproject
    elif name == 'config':
        from . import config
        return config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    '__version__',
    '__author__',
    '__license__',
]
