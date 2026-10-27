"""Game events (level-up, death) read from the game's log, Client.txt.

The file is only ever read, from where it ended when the app started: it can be several GB.
It is opened for each read and closed straight away, so the friend can still delete it
while the app runs. A file that got shorter or was replaced is read again from its start.

Line formats (English client), as matched by community log tools:
    2026/10/27 19:04:11 123456 cffb0734 [INFO Client 1234] : Name (Witch) is now level 92
    2026/10/27 19:05:02 123456 cffb0734 [INFO Client 1234] : Name has been slain.
    2026/10/27 19:05:40 123456 cffb0734 [INFO Client 1234] : Other has joined the area.
System messages start with ": " right after the bracket. Chat lines start with a name
instead ("Bob: hello"), so nobody can trigger an animation by typing in chat.

Whose character is whose: a name in a level-up line is one of the friend's characters,
unless that name was ever seen joining or leaving the area (only other players do that).
"""

import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

POLL_SECONDS = 0.5
RETRY_SECONDS = 5.0  # while the file is missing
MAX_READ = 1024 * 1024  # bytes per read; a burst of lines is caught up over a few reads
MAX_OTHERS = 500  # other players remembered

LINE = re.compile(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d .*?\[INFO Client \d+\] (: .*)$")
LEVEL = re.compile(r"^: (\S+) \(([^)]+)\) is now level (\d+)$")
SLAIN = re.compile(r"^: (\S+) has been slain\.$")
OTHER = re.compile(r"^: (\S+) has (?:joined|left) the area\.$")


@dataclass
class GameEvent:
    kind: str  # "levelup" or "death"
    name: str
    level: int | None = None


# --- Characters ------------------------------------------------------------------------------

class Characters:
    """The friend's characters as learned from the log, and the other players seen.

    characters.json: {"own": {name: {"enabled", "class", "level"}}, "others": [names]}
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.own: dict[str, dict] = {}
        self.others: list[str] = []
        self.lock = threading.Lock()
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.own = {str(k): {"enabled": bool(v.get("enabled", True)), "class": str(v.get("class", "")),
                                     "level": v.get("level") if isinstance(v.get("level"), int) else None}
                            for k, v in (data.get("own") or {}).items() if isinstance(v, dict)}
                self.others = [str(n) for n in data.get("others") or []][-MAX_OTHERS:]
            except (OSError, ValueError, AttributeError):
                log.warning("characters.json unreadable, starting again")

    def save(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"own": self.own, "others": self.others}, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def seen_other(self, name: str) -> None:
        with self.lock:
            if name in self.others:
                return
            self.others = (self.others + [name])[-MAX_OTHERS:]
            self.own.pop(name, None)  # it was a party member after all
            self.save()

    def levelled(self, name: str, char_class: str, level: int) -> bool:
        """Record a level-up. True if it is one of the friend's characters and is ticked."""
        with self.lock:
            if name in self.others:
                return False
            entry = self.own.setdefault(name, {"enabled": True, "class": char_class, "level": level})
            entry.update({"class": char_class, "level": level})
            self.save()
            return entry["enabled"]

    def is_own(self, name: str) -> bool:
        with self.lock:
            return self.own.get(name, {}).get("enabled", False)

    def set_enabled(self, name: str, enabled: bool) -> None:
        with self.lock:
            if name in self.own:
                self.own[name]["enabled"] = bool(enabled)
                self.save()

    def listing(self) -> list[dict]:
        with self.lock:
            return [{"name": n, **v} for n, v in sorted(self.own.items(), key=lambda kv: -(kv[1]["level"] or 0))]


def parse(line: str, characters: Characters) -> GameEvent | None:
    """One log line: a GameEvent for the friend's characters, else None (learning as it goes)."""
    m = LINE.match(line.rstrip("\r\n"))
    if not m:
        return None
    msg = m.group(1)
    if m := LEVEL.match(msg):
        name, level = m.group(1), int(m.group(3))
        return GameEvent("levelup", name, level) if characters.levelled(name, m.group(2), level) else None
    if m := SLAIN.match(msg):
        return GameEvent("death", m.group(1)) if characters.is_own(m.group(1)) else None
    if m := OTHER.match(msg):
        characters.seen_other(m.group(1))
    return None


# --- Finding Client.txt ----------------------------------------------------------------------

def candidate_paths() -> list[Path]:
    """Where the game usually is: the standalone install, then Steam and its other libraries."""
    out = []
    if sys.platform == "win32":
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                out.append(Path(base) / "Grinding Gear Games" / "Path of Exile" / "logs" / "Client.txt")
    for library in steam_libraries():
        out.append(library / "steamapps" / "common" / "Path of Exile" / "logs" / "Client.txt")
    return out


def steam_libraries() -> list[Path]:
    roots = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        roots.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam")
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "Steam")
    else:
        roots.append(Path.home() / ".local" / "share" / "Steam")
    libraries: list[Path] = []
    for root in roots:
        for lib in [root, *_library_folders(root / "steamapps" / "libraryfolders.vdf")]:
            if lib not in libraries:
                libraries.append(lib)
    return libraries


def _library_folders(vdf: Path) -> list[Path]:
    """The "path" entries of Steam's libraryfolders.vdf (other drives holding games)."""
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [Path(m.replace("\\\\", "\\")) for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def find_client_log(configured: str = "") -> Path | None:
    """The configured path, else the most recently written Client.txt found."""
    if configured:
        return Path(configured)
    found = [p for p in candidate_paths() if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


# --- Watching --------------------------------------------------------------------------------

class LogWatcher:
    """Follows Client.txt and reports GameEvents. `step()` does one read; the thread repeats it."""

    def __init__(self, locate: Callable[[], Path | None], characters: Characters,
                 on_event: Callable[[GameEvent], None]):
        self.locate = locate
        self.characters = characters
        self.on_event = on_event
        self.path: Path | None = None
        self.identity: tuple[int, int] | None = None
        self.pos = 0
        self.partial = b""
        self.found = False
        self.last_event: dict | None = None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="client-log")

    def start(self) -> "LogWatcher":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stopped.is_set():
            try:
                found = self.step()
            except Exception:
                log.exception("reading Client.txt failed")
                found = False
            self.stopped.wait(POLL_SECONDS if found else RETRY_SECONDS)

    def step(self) -> bool:
        """Read what was added since last time. False while there is no file to read."""
        path = self.locate()
        if path != self.path:
            self.path, self.identity, self.partial = path, None, b""
        if path is None:
            self.found = False
            return False
        try:
            st = path.stat()
        except OSError:
            self.found = False  # deleted: when it comes back, it is a new file read from the start
            return False
        self.found = True
        identity = (st.st_dev, st.st_ino)
        if self.identity is None:
            # First look at this file: start from its end, the past is not news.
            self.identity, self.pos, self.partial = identity, st.st_size, b""
            log.info("watching %s", path)
            return True
        if identity != self.identity or st.st_size < self.pos:
            log.info("%s was replaced or emptied, reading it from the start", path)
            self.identity, self.pos, self.partial = identity, 0, b""
        if st.st_size == self.pos:
            return True
        try:
            with open(path, "rb") as f:
                f.seek(self.pos)
                data = f.read(MAX_READ)
        except OSError:
            return False
        self.pos += len(data)
        *lines, self.partial = (self.partial + data).split(b"\n")
        for raw in lines:
            event = parse(raw.decode("utf-8", "replace"), self.characters)
            if event:
                self.last_event = {"kind": event.kind, "name": event.name, "level": event.level, "time": time.time()}
                try:
                    self.on_event(event)
                except Exception:
                    log.exception("game event handler failed")
        return True

    def status(self) -> dict:
        return {"path": str(self.path) if self.path else None, "found": self.found,
                "last_event": self.last_event}
