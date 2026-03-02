"""
App registry — manages which app is active and where each app's content lives.

Stores state in app_registry.json (gitignored). Each app writes its own
content_<name>.json file; the registry tracks which one /api/content should serve.
"""

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).parent / "app_registry.json"

DEFAULT_REGISTRY = {
    "active_app": "daily",
    "apps": {
        "daily": {"display_name": "Daily Pick", "content_file": "content_daily.json"},
        "ships": {"display_name": "Ship Tracker", "content_file": "content_ships.json"},
    },
}


def _load():
    try:
        with open(REGISTRY_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _save(DEFAULT_REGISTRY)
        return DEFAULT_REGISTRY.copy()


def _save(registry):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def get_active_app():
    """Return the name of the currently active app."""
    return _load()["active_app"]


def set_active_app(name):
    """Set the active app. Raises ValueError if unknown."""
    reg = _load()
    if name not in reg["apps"]:
        raise ValueError(f"Unknown app: {name}")
    reg["active_app"] = name
    _save(reg)


def list_apps():
    """Return dict of {name: {display_name, content_file}} for all apps."""
    return _load()["apps"]


def get_app_content_path(name):
    """Return the full Path to an app's content file."""
    reg = _load()
    if name not in reg["apps"]:
        raise ValueError(f"Unknown app: {name}")
    return Path(__file__).parent / reg["apps"][name]["content_file"]


def get_active_content():
    """Read and return the active app's content as a dict, or None."""
    reg = _load()
    path = Path(__file__).parent / reg["apps"][reg["active_app"]]["content_file"]
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
