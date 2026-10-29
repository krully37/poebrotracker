"""The map tracker: the maps the friend runs, read from Client.txt (docs/SCOPE.md §5c).

It reads the same lines as the game events: gamelog.LogWatcher hands each one over, so the file
is never opened a second time. The idea comes from Exile UI's map tracker (Lailloken/Exile-UI);
the code is our own.

Each area change writes a debug line, then a system line with the area's name:
    2026/10/27 19:04:11 123456 1186a886 [DEBUG Client 1234] Generating level 83 area "MapWorldsCitySquare" with seed 12345
    2026/10/27 19:04:12 123456 cffb06dd [INFO Client 1234] : You have entered City Square.
NPCs speak with their name right after the bracket, which tells the league mechanics of a map:
    2026/10/27 19:05:40 123456 cffb06dd [INFO Client 1234] Einhar, Beastmaster: Exile! ...
A chat line has a channel sign or a player's name there instead, and player names have no
spaces or commas, so nobody can fake most of these by typing.

- A **new map** starts when a map area is entered with another area id or another seed. The same
  seed again is the same map plus one portal (when entered from outside it, e.g. the hideout).
- **Side areas** (Abyss, the Vaal side area, lab trials, the Starfall crater) are part of the map
  they were entered from, and add a tag to it.
- **Map time** counts only inside the map and its side areas, and pauses once the PC has had no
  keyboard or mouse input for 10 s (Windows' idle clock, as for the idle cat).
"""

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import stats
from .gamelog import OPENING, Characters
from .idle import input_idle_seconds

log = logging.getLogger(__name__)

PAUSE_AFTER = 10.0  # seconds without input before the timer stops
MAX_STEP = 5.0  # a longer gap between two ticks (the PC asleep, the app stalled) is not counted
SAVE_EVERY = 60.0  # seconds between saves while a timer runs
KEEP_SECONDS = 14 * 24 * 3600  # like the stash history
MIN_RATE_SPAN = 15 * 60  # maps per hour shows once the session's maps span this long

_STAMP = r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d [^\[\]]*"
AREA = re.compile(_STAMP + r'\[DEBUG Client \d+\] Generating level (\d+) area "([^"]+)" with seed (\d+)$')
MESSAGE = re.compile(_STAMP + r"\[INFO Client \d+\] (.*)$")
ENTERED = re.compile(r"^: You have entered (.+)\.$")
DIED = re.compile(r"^: (\S+) (?:has been slain|has committed suicide)\.$")

# What counts as a map: area ids starting with these (any case), as in Exile UI.
MAP_AREAS = ("mapworlds", "maven", "betrayal", "incursion", "heist", "mapatziri", "legionleague", "expedition",
             "atlasexilesboss", "breachboss", "affliction", "bestiary", "sanctum", "synthesis", "azmeri",
             "harvestleagueboss", "chayulaleaguetowerboss", "faridunleagueboss", "mapatlasencounter")
NOT_MAPS = ("heisthub", "sanctumfoyer")  # the Rogue Harbour and the Sanctum's entrance are towns
# Side areas join the map they were entered from, with this tag.
SIDE_AREAS = {"abyssleague": "Abyss", "endgame_labyrinth_trials": "Trial", "mapsidearea": "Vaal area",
              "settlersbossfallenstar": "Starfall"}

SYNDICATE = ["Jun, Veiled Master", "Aisling Laffrey, The Silent Butcher", "Cameria the Coldblooded",
             "Elreon, Light's Judge", "Gravicius Reborn", 'Guff "Tiny" Grenn', "Haku, Warmaster",
             "Hillock, the Blacksmith", "It That Fled", "Janus Perandus", "Thane Jorgin the Banished",
             "Korell Goya, Son of Stone", "Leo, Wolf of the Pits", "Riker Maloney, Midnight Tinkerer",
             "Rin Yuushu", "Tora, the Culler", "Vagan, Victory's Herald", "Vorici, Silent Brother"]
# Who speaks -> the mechanic tag (English client).
MECHANICS = {
    "Einhar, Beastmaster": "Bestiary",
    "Niko, Master of the Depths": "Delve",
    "Alva, Master Explorer": "Incursion",
    "Strange Voice": "Delirium",
    **{name: "Betrayal" for name in SYNDICATE},
    "Sister Cassia": "Blight",
    "Oshabi": "Harvest",
    "The Trialmaster": "Ultimatum",
    "The Maven": "Maven",
    "Dannig, Warrior Skald": "Expedition",
    "Gwennen, the Gambler": "Expedition",
    "Rog": "Expedition",
    "Tujen, the Haggler": "Expedition",
}


def area_kind(area: str) -> str | None:
    """"map", "side" (a side area of a map), or None (hideout, town, campaign...)."""
    a = area.lower()
    for prefix, _ in SIDE_AREAS.items():
        if a.startswith(prefix):
            return "side"
    if a.startswith(MAP_AREAS) and not any(n in a for n in NOT_MAPS):
        return "map"
    return None


def tier(level: int) -> str:
    """Area level 83 is T16; below the maps' levels, the level itself."""
    return f"T{level - 67}" if level >= 68 else f"Level {level}"


@dataclass
class MapRun:
    area: str  # the game's area id, "MapWorldsCitySquare"
    seed: str
    level: int
    started: float  # unix time of the first entry
    name: str = ""  # "City Square", from the line after the area line
    seconds: float = 0.0  # time inside, without pauses
    portals: int = 1
    deaths: int = 0
    mechanics: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, d: dict) -> "MapRun":
        return cls(area=str(d["area"]), seed=str(d["seed"]), level=int(d["level"]), started=float(d["started"]),
                   name=str(d.get("name", "")), seconds=float(d.get("seconds", 0)), portals=int(d.get("portals", 1)),
                   deaths=int(d.get("deaths", 0)), mechanics=[str(m) for m in d.get("mechanics") or []])


@dataclass
class CurrentMap:
    """What the current-map card shows."""
    name: str
    tier: str
    seconds: float
    state: str  # "running", "paused" (no input for 10 s) or "out" (back in the hideout or elsewhere)
    deaths: int
    portals: int
    mechanics: list[str]


@dataclass
class MapStats:
    session: int
    today: int
    per_hour: float | None
    average: float | None  # seconds
    current: CurrentMap | None


class MapTracker:
    """Follows the maps from Client.txt lines (`feed`) and counts their time (`tick`, once a second).

    maps.json: {"maps": [MapRun...]}; the last one is the current map.
    """

    def __init__(self, path: Path | None, characters: Characters,
                 idle_seconds: Callable[[], float | None] = input_idle_seconds,
                 clock: Callable[[], float] = time.time):
        self.path = path
        self.characters = characters
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.maps: list[MapRun] = []
        self.inside = False  # in the current map or one of its side areas
        self.paused = False  # inside, but the PC has been idle for 10 s
        self.on_change: Callable[[], None] | None = None  # something the card shows changed
        self.on_back: Callable[[], None] | None = None  # back out of a map (hideout, town...)
        self.lock = threading.RLock()
        self._naming: MapRun | None = None  # a new map waiting for its "You have entered" line
        self._last_tick: float | None = None
        self._last_save = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def load(cls, path: Path | None, characters: Characters, **kwargs) -> "MapTracker":
        tracker = cls(path, characters, **kwargs)
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tracker.maps = [MapRun.from_json(d) for d in data.get("maps") or []]
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                log.warning("maps.json unreadable, starting again")
        # Where the friend is when the app starts is unknown until the next area change.
        return tracker

    def save(self) -> None:
        if self.path is None:
            return
        with self.lock:
            text = json.dumps({"maps": [asdict(m) for m in self.maps]}, separators=(",", ":"))
            self._last_save = self.clock()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def current(self) -> MapRun | None:
        return self.maps[-1] if self.maps else None

    # --- Lines ---------------------------------------------------------------------------

    def feed(self, line: str) -> None:
        """One Client.txt line."""
        line = line.rstrip("\r\n")
        changed = back = False
        with self.lock:
            if m := AREA.match(line):
                changed, back = self._enter(int(m.group(1)), m.group(2), m.group(3))
            elif OPENING.match(line):
                # The game (re)started: the friend is at the login screen, not in a map.
                self._tick(self.clock())
                changed, self.inside, self._naming = self.inside, False, None
            elif m := MESSAGE.match(line):
                changed = self._message(m.group(1))
        if changed:
            self.save()
            self._notify(self.on_change)
        if back:
            self._notify(self.on_back)

    def _enter(self, level: int, area: str, seed: str) -> tuple[bool, bool]:
        """An area change. Returns (the card changed, back out of a map)."""
        now = self.clock()
        self._tick(now)  # the time up to here belongs to the area being left
        self._naming = None
        kind = area_kind(area)
        was_inside, cur = self.inside, self.current
        if kind == "map":
            same = cur is not None and cur.area == area and (cur.seed == seed or area.lower().startswith("sanctum"))
            if same:
                if not was_inside:
                    cur.portals += 1  # back in through a portal (not from one of its side areas)
            else:
                self._new_map(MapRun(area, seed, level, now))
            self.inside = True
            return True, False
        if kind == "side":
            if cur is None:
                self._new_map(MapRun(area, seed, level, now))  # nothing to join: a map of its own
            tag = next(t for prefix, t in SIDE_AREAS.items() if area.lower().startswith(prefix))
            if tag not in self.current.mechanics:
                self.current.mechanics.append(tag)
            self.inside = True
            return True, False
        self.inside = False
        return was_inside, was_inside

    def _new_map(self, run: MapRun) -> None:
        self.maps.append(run)
        self._naming = run
        cutoff = run.started - KEEP_SECONDS
        if self.maps[0].started < cutoff:
            self.maps = [m for m in self.maps if m.started >= cutoff]

    def _message(self, msg: str) -> bool:
        cur = self.current
        if msg.startswith(": "):
            if (m := ENTERED.match(msg)) and self._naming is not None:
                self._naming.name, self._naming = m.group(1), None
                return True
            if (m := DIED.match(msg)) and self.inside and cur and self.characters.is_own(m.group(1)):
                cur.deaths += 1
                return True
            return False
        if not self.inside or cur is None:
            return False
        speaker = msg.split(": ", 1)[0] if ": " in msg else None
        tag = MECHANICS.get(speaker) if speaker else None
        if tag and tag not in cur.mechanics:
            cur.mechanics.append(tag)
            return True
        return False

    # --- Time -----------------------------------------------------------------------------

    def tick(self) -> bool:
        """Count the time since the last tick. True when the timer's whole seconds changed."""
        now = self.clock()
        with self.lock:
            cur = self.current
            before = int(cur.seconds) if cur else None
            paused_before = self.paused
            self._tick(now)
            after = int(cur.seconds) if cur else None
            due = self.inside and now - self._last_save >= SAVE_EVERY
        if due:
            self.save()
        return before != after or paused_before != self.paused

    def _tick(self, now: float) -> None:
        last, self._last_tick = self._last_tick, now
        if not self.inside or self.current is None:
            self.paused = False
            return
        idle = self.idle_seconds()
        self.paused = idle is not None and idle >= PAUSE_AFTER
        if last is None or self.paused:
            return
        step = now - last
        if 0 < step <= MAX_STEP:
            self.current.seconds += step

    def start(self, on_tick: Callable[[bool], None] | None = None) -> "MapTracker":
        """Tick once a second on a thread; on_tick(timer changed) after each tick."""
        def run() -> None:
            while not self._stop.wait(1.0):
                try:
                    changed = self.tick()
                    if on_tick:
                        on_tick(changed)
                except Exception:
                    log.exception("map tracker tick failed")

        self._thread = threading.Thread(target=run, daemon=True, name="map-tracker")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    # --- Numbers --------------------------------------------------------------------------

    def has_maps(self) -> bool:
        return bool(self.maps)

    def stats(self, session_start: float, now: float) -> MapStats:
        """Maps this session (the same session as div/h) and today (since local midnight)."""
        with self.lock:
            session = [m for m in self.maps if m.started >= session_start]
            today = [m for m in self.maps if m.started >= stats.local_midnight(now)]
            cur = self.current
            running = cur if self.inside else None
            done = [m.seconds for m in session if m is not running]
            per_hour = None
            if session and now - session[0].started >= MIN_RATE_SPAN:
                per_hour = len(session) / (now - session[0].started) * 3600
            current = None
            if cur is not None:
                current = CurrentMap(cur.name or cur.area, tier(cur.level), cur.seconds,
                                     "out" if not self.inside else "paused" if self.paused else "running",
                                     cur.deaths, cur.portals, list(cur.mechanics))
            return MapStats(len(session), len(today), per_hour, sum(done) / len(done) if done else None, current)

    def _notify(self, callback: Callable[[], None] | None) -> None:
        if callback:
            try:
                callback()
            except Exception:
                log.exception("map tracker listener failed")


def demo_stats() -> MapStats:
    """Made-up numbers for previews, until the friend has run a map."""
    return MapStats(session=12, today=17, per_hour=6.4, average=7 * 60 + 48,
                    current=CurrentMap("City Square", "T16", 4 * 60 + 12, "running", 0, 1, ["Bestiary", "Delirium"]))
