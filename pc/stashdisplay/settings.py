"""settings.json: the app's settings, the pages, the sealed cookie and the settings-page token.

Everything the settings page edits lives here. Values are checked and clamped
on load and on save, so a hand-edited or old file never breaks the app.
"""

import copy
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import pages as pagelib
from . import vault

LANGUAGES = ["en", "fr"]

DEFAULTS: dict = {
    "language": "en",
    "interval": 300,               # seconds between WealthyExile fetches
    "min_refresh_interval": 60,    # a tap on the screen never fetches sooner than this
    "rate_window_minutes": 60,     # div/h is computed over this window
    "spark_points": 48,            # points in the sparkline (48 x 5 min = 4 h)
    "new_session_on_start": True,
    "poeninja": {"enabled": True, "interval": 1800},
    "serial": {"port": ""},        # "" = detect the screen automatically
    # Game events from Client.txt, and "boot": the screen's start animation (power-on, and each
    # time the PC connects). "media": an uploaded file id, "" = the built-in animation.
    "events": {
        "client_log": "",          # "" = find Client.txt automatically
        "boot": {"enabled": True, "media": ""},
        "launch": {"enabled": True, "media": ""},
        "levelup": {"enabled": True, "media": ""},
        "death": {"enabled": True, "media": ""},
    },
    # The idle cat: after this many minutes without keyboard or mouse input (and no media
    # playing), the screen shows the cat bouncing around instead of the pages.
    "idle": {"enabled": True, "minutes": 10},
    "web": {"port": 47821},
}

# (key path, minimum, maximum) for numbers. The minimums keep requests spaced out.
LIMITS = [
    (("interval",), 60, 3600),
    (("min_refresh_interval",), 30, 600),
    (("rate_window_minutes",), 15, 360),
    (("spark_points",), 8, 288),
    (("poeninja", "interval"), 900, 86400),
    (("idle", "minutes"), 1, 120),
    (("web", "port"), 1024, 65535),
]


def _merge(defaults: dict, given: dict) -> dict:
    out = {}
    for key, default in defaults.items():
        value = given.get(key, copy.deepcopy(default)) if isinstance(given, dict) else copy.deepcopy(default)
        if isinstance(default, dict):
            out[key] = _merge(default, value if isinstance(value, dict) else {})
        elif isinstance(default, bool):
            out[key] = bool(value)
        elif isinstance(default, int):
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                out[key] = default
        else:
            out[key] = str(value) if value is not None else default
    return out


def normalize_settings(given: dict) -> dict:
    s = _merge(DEFAULTS, given or {})
    for path, lo, hi in LIMITS:
        node = s
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = min(max(node[path[-1]], lo), hi)
    if s["language"] not in LANGUAGES:
        s["language"] = "en"
    return s


@dataclass
class Store:
    path: Path
    settings: dict = field(default_factory=lambda: normalize_settings({}))
    pages: list[dict] = field(default_factory=pagelib.preset)
    cookie: str = ""
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    @classmethod
    def load(cls, path: Path) -> "Store":
        if not path.exists():
            store = cls(path=path)
            store.save()
            return store
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = [pagelib.normalize_page(p) for p in data.get("pages", [])] or pagelib.preset()
        return cls(
            path=path,
            settings=normalize_settings(data.get("settings", {})),
            pages=pages,
            cookie=vault.unseal(data.get("cookie")),
            token=data.get("token") or secrets.token_urlsafe(24),
        )

    def save(self) -> None:
        data = {
            "version": 1,
            "settings": self.settings,
            "pages": self.pages,
            "cookie": vault.seal(self.cookie),
            "token": self.token,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)  # the cookie is only base64 off Windows
        os.replace(tmp, self.path)

    def update(self, settings: dict | None = None, pages: list[dict] | None = None) -> None:
        if settings is not None:
            self.settings = normalize_settings(settings)
        if pages is not None:
            self.pages = [pagelib.normalize_page(p) for p in pages]
            # Ids must be unique: the screen and the editor use them to tell pages apart.
            seen: set[str] = set()
            for p in self.pages:
                while p["id"] in seen:
                    p["id"] = secrets.token_hex(4)
                seen.add(p["id"])
        self.save()
