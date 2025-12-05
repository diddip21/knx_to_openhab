# utils.py
"""Utility functions for KNX to OpenHAB conversion."""

from config import config

def get_datapoint_type(key: str) -> str:
    """Return the DPST string for a given logical key.

    The mapping is defined in ``config['datapoint_types']``.
    Raises ``KeyError`` if the key is missing.
    """
    try:
        return config["datapoint_types"][key]
    except KeyError as exc:
        raise KeyError(f"Datapoint type key '{key}' not found in config['datapoint_types']") from exc
