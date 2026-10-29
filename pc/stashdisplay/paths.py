"""Per-user folders for the config, history, logs and dumps.

Windows: %APPDATA%\\stashdisplay
macOS:   ~/Library/Application Support/stashdisplay
Linux:   $XDG_CONFIG_HOME/stashdisplay (or ~/.config/stashdisplay)
"""

import os
import sys
from pathlib import Path

APP_NAME = "stashdisplay"


def app_dir() -> Path:
    override = os.environ.get("STASHDISPLAY_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return app_dir() / "settings.json"


def history_path() -> Path:
    return app_dir() / "history.json"


def characters_path() -> Path:
    return app_dir() / "characters.json"


def maps_path() -> Path:
    return app_dir() / "maps.json"


def log_path() -> Path:
    return app_dir() / "stashdisplay.log"


def dump_dir() -> Path:
    path = app_dir() / "dumps"
    path.mkdir(exist_ok=True)
    return path
