"""The running app: settings, assets, media, history, the data shown on the pages, the screen,
and the game events read from Client.txt.

The settings page, the tray and the screen link all talk to one App. Until the WealthyExile
step, the history is demo data that grows by one point every 5 minutes, so the screen and
the simulator show something that moves and can be reset.
"""

import dataclasses
import io
import logging
import threading
import time
from collections.abc import Callable

from . import paths
from .assets import AssetCache
from .gamelog import Characters, GameEvent, LogWatcher, find_client_log
from .link import protocol
from .link.client import Content, ScreenLink
from .link.content import ContentBuilder
from .link.transport import Port, SerialPort, candidate_ports
from .media import MediaStore
from .nowplaying import ACTIONS as MEDIA_ACTIONS
from .nowplaying import Player, create_player
from .render import data as renderdata
from .render import fonts, renderer, theme
from .settings import Store

log = logging.getLogger(__name__)

TOASTS = {"reset_session": "Session reset", "reset_rate": "Div/h reset"}
EVENT_KINDS = ("launch", "levelup", "death")
# "boot" is the start animation: the screen plays it at power-on, the PC each time it connects.
ANIM_KINDS = ("boot", *EVENT_KINDS)
CARD_SECONDS = 4.0  # the text stand-in for an event without a GIF


class App:
    def __init__(self, store: Store, assets: AssetCache, media: MediaStore, characters: Characters | None = None):
        self.store = store
        self.assets = assets
        self.media = media
        self.live_data: renderdata.RenderData | None = None
        self.status = {"screen": "disconnected", "last_sync": None, "error": None}
        self.on_save: list[Callable[[], None]] = [self._screen_sync]
        self._render_lock = threading.RLock()  # Pillow fonts are not safe to share across threads
        self._data_lock = threading.RLock()
        self._demo_source = None
        self.history = None
        self.last_snapshot = None
        self.content = ContentBuilder(media)
        self.link: ScreenLink | None = None
        self.simulator = None  # (SimScreen, LoopbackPair) when started with --simulator
        self.characters = characters or Characters(None)
        self.watcher: LogWatcher | None = None
        self.fake_log = None  # with --simulator: a test Client.txt the simulator page writes to
        # event kind -> (screen file id, seconds, over the page)
        self.anim_files: dict[str, tuple[str, float, bool]] = {}
        self._playing: tuple[str, float] | None = None  # (event kind, monotonic end)
        self.player: Player | None = None  # what the PC plays, for the media card

    @classmethod
    def create(cls, offline: bool = False) -> "App":
        store = Store.load(paths.settings_path())
        assets = AssetCache(offline=offline)
        app = cls(store, assets, MediaStore(paths.app_dir() / "media"), Characters(paths.characters_path()))
        fonts.register_fontin(assets.fontin())
        return app

    def _demo_tick(self, now: float) -> None:
        """Start the demo history, then add a point every 5 minutes like a real fetch would."""
        from .cli import demo_history  # import here: cli imports this module

        if self._demo_source is None:
            # The last point is a couple of minutes old, like a real fetch would be.
            self.history, self._demo_source, self.last_snapshot = demo_history(now - 130, seed=7)
            return
        while self._demo_source.sim_time + self._demo_source.step <= now:
            self._add(self._demo_source.fetch())

    def _add(self, snap) -> None:
        self.history.add(snap.time, snap.total, snap.league)
        self.last_snapshot = snap

    def render_data(self, force_demo: bool = False) -> tuple[renderdata.RenderData, bool]:
        """Data for a render, and whether it is demo data."""
        from .cli import demo_prices

        now = time.time()
        media = self.player.now() if self.player else None
        if self.live_data is not None and not force_demo:
            return dataclasses.replace(self.live_data, now=now, media=media), False
        with self._data_lock:
            self._demo_tick(now)
            snap = self.last_snapshot
            s = self.store.settings
            data = renderdata.build(
                self.history, snap, now=now, synced_at=snap.time, item_prices=demo_prices(snap.div_price),
                spark_points=s["spark_points"], rate_window=s["rate_window_minutes"] * 60, icon=self.assets.icon,
            )
        return dataclasses.replace(data, media=media), True

    # --- Screen ---------------------------------------------------------------------------

    def start_link(self, ports: Callable[[], list[Port]] | None = None) -> ScreenLink:
        """Connect to the screen: the given ports (the simulator), else USB serial ports."""
        self.link = ScreenLink(ports or self._serial_ports, self.screen_content, self.on_screen_event,
                               on_connect=self._screen_connected).start()
        return self.link

    def _screen_connected(self, inventory: dict) -> None:
        """The start animation, unless the screen is already playing it (it just powered on)."""
        if "boot" in self.anim_files and inventory.get("playing") != protocol.BOOT_FILE:
            self.play_event("boot", "", force=True)

    def _serial_ports(self) -> list[Port]:
        out = []
        for device in candidate_ports(self.store.settings["serial"]["port"]):
            try:
                out.append(SerialPort(device))
            except OSError as e:
                log.debug("cannot open %s: %s", device, e)
        return out

    def screen_content(self) -> Content:
        data, _ = self.render_data()
        with self._render_lock:
            content = self.content.build(self.store.pages, data)
            anim_files = {}
            for kind in ANIM_KINDS:
                opts = self.store.settings["events"][kind]
                anim = self.content.animation(kind, opts["media"]) if opts["enabled"] else None
                if anim:
                    file_id, f, seconds = anim
                    boot = content.files.get(protocol.BOOT_FILE)
                    if boot and boot.crc == f.crc:
                        file_id = protocol.BOOT_FILE  # the same animation: one copy on the screen
                    content.files[file_id] = f
                    anim_files[kind] = (file_id, seconds, f.over_page)
            self.anim_files = anim_files
        return content

    def _screen_sync(self) -> None:
        if self.link:
            self.link.request_sync()

    def toast(self, text: str) -> None:
        if self.link:
            with self._render_lock:
                self.link.toast(protocol.encode_overlay(renderer.toast(text)))

    def on_screen_event(self, event: dict) -> None:
        kind = event.get("type")
        now = time.time()
        if kind == "tap" and event.get("action") in MEDIA_ACTIONS:
            if self.player:
                self.player.command(event["action"])  # the card follows through on_change
            return
        if kind == "tap":
            with self._data_lock:
                last = self.last_snapshot.time if self.last_snapshot else 0
                if now - last < self.store.settings["min_refresh_interval"]:
                    self.toast("Too soon")
                    return
                self.refresh(now)
            self._screen_sync()
        elif kind == "reset" and event.get("action") in TOASTS:
            with self._data_lock:
                self._demo_tick(now)
                if event["action"] == "reset_session":
                    self.history.start_session(now)
                else:
                    self.history.rate_start = now
                self.history.save()
            self.toast(TOASTS[event["action"]])
            self._screen_sync()

    # --- Media card ----------------------------------------------------------------------

    def start_player(self, fake: bool = False) -> Player:
        self.player = create_player(fake)
        self.player.on_change = self._media_changed
        return self.player.start()

    def _media_changed(self) -> None:
        """A new track, cover, or play/pause: update the screen, if a page shows the card."""
        if any(slot and slot["widget"] == "media"
               for page in self.store.pages if not page["hidden"] for slot in page["slots"].values()):
            self._screen_sync()

    # --- Game events ---------------------------------------------------------------------

    def client_log(self):
        """Client.txt: the configured path, else the simulator's test log, else the one found."""
        configured = self.store.settings["events"]["client_log"]
        if not configured and self.fake_log is not None:
            return self.fake_log
        return find_client_log(configured)

    def start_watcher(self) -> LogWatcher:
        self.watcher = LogWatcher(self.client_log, self.characters, self.on_game_event).start()
        return self.watcher

    def on_game_event(self, event: GameEvent) -> None:
        if self.store.settings["events"][event.kind]["enabled"]:
            self.play_event(event.kind, event.name, event.level)

    def play_event(self, kind: str, name: str, level: int | None = None, force: bool = False) -> bool:
        """The animation for an event, full screen or over the page. The newest replaces the one
        playing, except that a level-up never cuts a death short. False when the screen is not there."""
        now = time.monotonic()
        if not force and kind == "levelup" and self._playing and self._playing[0] == "death" and now < self._playing[1]:
            return False
        if not self.link:
            return False
        file_id, seconds, over_page = self.anim_files.get(kind, (None, CARD_SECONDS, False))
        if file_id and self.link.has_file(file_id):
            played = self.link.play(file_id, None, seconds, over_page)
        else:
            # No GIF on the screen (none made yet, or no room): large text instead.
            title = {"boot": "Stash Display", "launch": "Path of Exile", "levelup": f"Level {level}"}.get(kind, "Slain")
            with self._render_lock:
                card = renderer.event_card(title, name, color=theme.DEATH if kind == "death" else theme.TITLE)
                overlay = protocol.encode_overlay(card)
            seconds = CARD_SECONDS
            played = self.link.play(None, overlay, seconds)
        if played:
            self._playing = (kind, now + seconds)
        return played

    def events_status(self) -> dict:
        return {**(self.watcher.status() if self.watcher else {"path": None, "found": False, "last_event": None}),
                "characters": self.characters.listing()}

    def refresh(self, now: float) -> None:
        """Fetch new data now. Demo: one more point, timed now."""
        self._demo_tick(now)
        src = self._demo_source
        src.sim_time = now - src.step  # fetch() steps forward, so the point lands exactly now
        self._add(src.fetch())

    def preview_png(self, page: dict, index: int, count: int, force_demo: bool = False) -> tuple[bytes, bool]:
        data, is_demo = self.render_data(force_demo)
        with self._render_lock:
            img = renderer.preview(page, data, index, count, still_for=self.media.still_path)
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=1)  # fast: this goes to a browser on the same PC
        return buf.getvalue(), is_demo

    def save(self, settings: dict | None, pages: list[dict] | None) -> None:
        self.store.update(settings=settings, pages=pages)
        for callback in self.on_save:
            try:
                callback()
            except Exception:  # a failing listener must not lose the user's save
                log.exception("on_save listener failed")
