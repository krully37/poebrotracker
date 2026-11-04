"""The running app: settings, assets, media, history, the data shown on the pages, the screen,
the game events read from Client.txt, and the idle cat.

The settings page, the tray and the screen link all talk to one App. The stash comes from
WealthyExile once a cookie is saved and it has answered; until then the pages show demo data that
grows by one point every 5 minutes, so the screen and the simulator show something that moves.
"""

import dataclasses
import hashlib
import io
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import maps as mapslib
from . import pages as pagelib
from . import paths
from .assets import AssetCache
from .gamelog import Characters, GameEvent, LogWatcher, find_client_log
from .history import History
from .idle import IdleWatch
from .link import protocol
from .link.client import Content, PageContent, ScreenLink
from .link.content import ContentBuilder
from .link.transport import Port, SerialPort, candidate_ports
from .maps import MapTracker
from .media import MediaStore
from .nowplaying import ACTIONS as MEDIA_ACTIONS
from .nowplaying import Player, create_player
from .render import data as renderdata
from .render import fonts, renderer, theme
from .settings import Store
from .sources import ninja, poepricer, wealthyexile
from .sources.base import AuthError, Snapshot, SourceError, rescaled

log = logging.getLogger(__name__)

TOASTS = {"reset_session": "Session reset", "reset_rate": "Div/h reset"}
SYNCING = "Syncing WealthyExile..."  # the toast for a tap that syncs
HOLDING = {"reset_session": "Resetting session", "reset_rate": "Resetting div/h"}  # the banner while held
EVENT_KINDS = ("launch", "levelup", "death")
# "boot" is the start animation: the screen plays it at power-on, the PC each time it connects.
ANIM_KINDS = ("boot", *EVENT_KINDS)
CARD_SECONDS = 4.0  # the text stand-in for an event without a GIF
SYNC_WAIT = 30.0  # seconds between syncing WealthyExile and reading it again (a sync took ~25 s)
MAP_SYNC_EVERY = 300.0  # back from a map, WealthyExile is synced at most this often (docs/SCOPE.md §5c)


class App:
    def __init__(self, store: Store, assets: AssetCache, media: MediaStore, characters: Characters | None = None,
                 history: History | None = None, maps: MapTracker | None = None):
        self.store = store
        self.assets = assets
        self.media = media
        self.status = {"last_sync": None, "error": None}  # the screen's state is self.link.state
        self.on_save: list[Callable[[], None]] = [self._screen_sync]
        self._render_lock = threading.RLock()  # Pillow fonts are not safe to share across threads
        self._data_lock = threading.RLock()
        # Demo data, until WealthyExile answers.
        self._demo_source = None
        self._demo_history = None
        self._demo_snapshot = None
        # The real stash: live once WealthyExile has given a snapshot.
        self.live = False
        self.history = history or History()  # in memory unless given (App.create loads the saved one)
        self.last_snapshot = None
        self.last_fetch = 0.0  # when WealthyExile was last read (a tap reads again, at most every minute)
        self.last_we_sync = 0.0  # when WealthyExile was last synced (a tap, or after a map)
        self._map_sync_pending = False  # back from a map: sync when 5 minutes have passed since the last one
        # A hash of the cookie WealthyExile turned down: nothing more is asked with it (docs/SCOPE.md §6).
        self._expired_cookie: str | None = None
        self._fetch_now = threading.Event()
        self._fetcher: threading.Thread | None = None
        self.prices = ninja.Prices(assets, store.settings["poeninja"]["interval"])
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
        self.idle: IdleWatch | None = None
        # The maps run, from the same Client.txt lines (docs/SCOPE.md §5c).
        self.maps = maps or MapTracker(None, self.characters)
        self.maps.on_change = self._screen_sync  # a new map, a portal, a death, a mechanic...
        self.maps.on_back = self._back_from_map

    @classmethod
    def create(cls, offline: bool = False, assets_root: Path | None = None) -> "App":
        store = Store.load(paths.settings_path())
        assets = AssetCache(assets_root, offline=offline)
        characters = Characters(paths.characters_path())
        app = cls(store, assets, MediaStore(paths.app_dir() / "media"), characters,
                  History.load(paths.history_path()), MapTracker.load(paths.maps_path(), characters))
        fonts.register_fontin(assets.fontin())
        return app

    def _demo_tick(self, now: float) -> None:
        """Start the demo history, then add a point every 5 minutes like a real fetch would."""
        from .cli import demo_history  # import here: cli imports this module

        if self._demo_source is None:
            # The last point is a couple of minutes old, like a real fetch would be.
            self._demo_history, self._demo_source, self._demo_snapshot = demo_history(now - 130, seed=7)
            return
        while self._demo_source.sim_time + self._demo_source.step <= now:
            self._demo_add(self._demo_source.fetch())

    def _demo_add(self, snap) -> None:
        self._demo_history.add(snap.time, snap.total, snap.league)
        self._demo_snapshot = snap

    def _shown(self, now: float, force_demo: bool = False) -> tuple[History, Snapshot]:
        """The history and snapshot the pages show: the real ones once live, else demo data."""
        if self.live and not force_demo:
            return self.history, self.last_snapshot
        self._demo_tick(now)
        return self._demo_history, self._demo_snapshot

    # --- WealthyExile ----------------------------------------------------------------------

    def start_fetching(self) -> threading.Thread:
        """Read WealthyExile every `interval` seconds while a cookie is saved, and on request."""
        def run() -> None:
            while True:
                self._fetch_now.wait(5)
                asked = self._fetch_now.is_set()
                self._fetch_now.clear()
                self._fetch_turn(asked, time.time())

        self._fetcher = threading.Thread(target=run, daemon=True, name="wealthyexile")
        self._fetcher.start()
        return self._fetcher

    def _fetch_turn(self, asked: bool, now: float) -> None:
        """One turn of the fetcher (every 5 s): sync WealthyExile first when a tap asked for it or
        a map is over, then read the stash; otherwise read it every `interval` seconds."""
        s = self.store.settings
        new_cookie = self._expired_cookie is not None and bool(self.store.cookie) and not self._cookie_expired()
        if new_cookie:
            self._expired_cookie = None  # another cookie was saved: read with it now
        after_map = self._map_sync_due(now)
        if not self._can_fetch() or not (asked or after_map or new_cookie or now - self.last_fetch >= s["interval"]):
            return
        error = self.status["error"]
        waited = 0.0
        if (asked or after_map) and s["source"] == "wealthyexile":
            self.last_we_sync, self._map_sync_pending = now, False  # this sync covers the map too
            if self.sync_wealthyexile():
                time.sleep(SYNC_WAIT)  # WealthyExile reads the stash from GGG meanwhile
                waited = SYNC_WAIT
        fetched = not self._cookie_expired() and self.fetch(now + waited)
        if s["poeninja"]["enabled"] and self.live:
            self.prices.refresh(self._priced_items(), self._league())  # only when 30 min old
        if fetched or self.status["error"] != error:
            self._screen_sync()  # new values, or the top bar's error appears or changes

    def _cookie_key(self) -> str:
        return hashlib.sha256(self.store.cookie.encode()).hexdigest()

    def _cookie_expired(self) -> bool:
        """WealthyExile turned the saved cookie down: wait for another one, asking nothing."""
        return (self.store.settings["source"] == "wealthyexile" and self._expired_cookie is not None
                and self._expired_cookie == self._cookie_key())

    def _turned_down(self) -> None:
        self._expired_cookie = self._cookie_key()
        log.info("WealthyExile: cookie expired; not asking again until a new one is saved")

    def _back_from_map(self) -> None:
        """Back in the hideout (or a town) after a map: sync WealthyExile so div per map stays
        current without a tap (docs/SCOPE.md §5c). The fetcher does it within 5 s, or once 5
        minutes have passed since the last sync."""
        if self.store.settings["maps"]["sync_after_map"]:
            self._map_sync_pending = True

    def _map_sync_due(self, now: float) -> bool:
        s = self.store.settings
        return (self._map_sync_pending and s["maps"]["sync_after_map"] and s["source"] == "wealthyexile"
                and bool(self.store.cookie) and not self._cookie_expired() and now - self.last_we_sync >= MAP_SYNC_EVERY)

    def sync_wealthyexile(self) -> bool:
        """What WealthyExile's "Sync stash" button does: on a tap, and back from a map at most
        every 5 minutes (docs/SCOPE.md §6, §5c). False when it failed; the read that follows
        still happens."""
        try:
            wealthyexile.sync(self.store.cookie)
        except SourceError as e:
            log.info("WealthyExile sync: %s", e.short)  # never the reply: it can carry the session
            if isinstance(e, AuthError):
                self._turned_down()
                self.status["error"] = e.short
            return False
        log.info("WealthyExile sync sent")
        return True

    def _priced_items(self) -> list[str]:
        """Every item chosen in an item-price card on a shown page."""
        names = []
        for page in pagelib.visible(self.store.pages):
            for slot in (page.get("slots") or {}).values():
                if slot and slot.get("widget") == "item_price":
                    names += [n for n in slot.get("items") or [] if n not in names]
        return names

    def _can_fetch(self) -> bool:
        return self.store.settings["source"] == "poe-pricer" or (bool(self.store.cookie) and not self._cookie_expired())

    def _league(self) -> str:
        """The league to ask PoE Pricer about: WealthyExile's once known, else poe.ninja's current one."""
        return (self.last_snapshot.league if self.last_snapshot else "") or self.assets.league()

    def fetch(self, now: float) -> bool:
        """Read the stash once, from the chosen source. A failure keeps the last good values and
        says why in the status."""
        self.last_fetch = now
        url = self.store.settings["poepricer"]["url"]
        try:
            if self.store.settings["source"] == "poe-pricer":
                snap = poepricer.fetch(self._league(), url, now=now,
                                       unique_tabs=self.store.settings["poepricer"]["unique_tabs"])
            else:
                snap = wealthyexile.fetch(self.store.cookie, now)
                # PoE Pricer, when it answers, is the first source for the divine price.
                rate = poepricer.divine_price(snap.league, url) if poepricer.running(url) else None
                if rate and snap.div_price:
                    snap = rescaled(snap, snap.div_price / rate, rate)
        except SourceError as e:
            log.info("stash source: %s", e.short)  # never WealthyExile's reply: it can carry the session
            if isinstance(e, AuthError) and self.store.settings["source"] == "wealthyexile":
                self._turned_down()
            self.status["error"] = e.short
            return False
        with self._data_lock:
            self.history.add(snap.time, snap.total, snap.league)  # one point per WealthyExile sync
            self.history.save()
            self.last_snapshot = snap
            self.live = True
        self.status["error"] = None
        self.status["last_sync"] = snap.time
        log.info("stash read: synced at %s", time.strftime("%H:%M:%S", time.localtime(snap.time)))
        return True

    def render_data(self, force_demo: bool = False) -> tuple[renderdata.RenderData, bool]:
        """Data for a render, and whether it is demo data."""
        from .cli import demo_prices

        now = time.time()
        media = self.player.now() if self.player else None
        with self._data_lock:
            history, snap = self._shown(now, force_demo)
            demo = history is self._demo_history
            s = self.store.settings
            # Maps come from Client.txt, not the stash: real ones as soon as there is one. They
            # count in the session shown, so a hold on the session value resets both.
            if force_demo or (demo and not self.maps.has_maps()):
                map_stats = mapslib.demo_stats()
            else:
                map_stats = self.maps.stats(history.session_start, now)
            data = renderdata.build(
                history, snap, now=now, synced_at=snap.time,
                item_prices=demo_prices(snap.div_price) if demo else self.prices.get(self._priced_items(), snap.league, snap.div_price),
                spark_points=s["spark_points"], rate_window=s["rate_window_minutes"] * 60, icon=self.assets.icon, kind=self.assets.kind,
                maps=map_stats,
            )
        # The settings page's forced demo preview says nothing of the real stash's state.
        return dataclasses.replace(data, media=media, error=None if force_demo else self.status["error"]), demo

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
            sprite = self.content.idle_sprite() if self.store.settings["idle"]["enabled"] else None
            if sprite:
                content.files[protocol.IDLE_FILE] = sprite
            content.overlays = self._hold_banners()
        return content

    def _hold_banners(self) -> dict[str, bytes]:
        # Rendered at each sync, so they follow the font once Fontin is downloaded.
        return {protocol.HOLD_OVERLAY + action: protocol.encode_overlay(renderer.hold_banner(text))
                for action, text in HOLDING.items()}

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
        if kind == "wake":
            if self.idle:
                self.idle.wake()  # the cat goes for a minute; the screen already shows the pages
            return
        if kind == "tap" and event.get("action") in MEDIA_ACTIONS:
            if self.player:
                self.player.command(event["action"])  # the card follows through on_change
            return
        if kind == "tap":
            if self._cookie_expired():
                return  # the top bar already says "Cookie expired": a sync could not work
            with self._data_lock:
                last = self.last_fetch if self.live else (self._demo_snapshot.time if self._demo_snapshot else 0)
                if now - last < self.store.settings["min_refresh_interval"]:
                    return  # too soon: nothing shows, the data is fresh anyway (owner, 2026-10-29)
                self.refresh(now)
            if self.live and self.store.settings["source"] == "wealthyexile":
                self.toast(SYNCING)  # the new values take ~30 s: say something has started
            self._screen_sync()
        elif kind == "reset" and event.get("action") in TOASTS:
            with self._data_lock:
                history, _ = self._shown(now)
                if event["action"] == "reset_session":
                    history.start_session(now)
                else:
                    history.rate_start = now
                history.save()
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

    # --- Idle cat ------------------------------------------------------------------------

    def start_idle(self) -> IdleWatch:
        self.idle = IdleWatch(lambda: self.store.settings["idle"], self._media_playing, self._idle_changed).start()
        return self.idle

    def _media_playing(self) -> bool:
        now = self.player.now() if self.player else None
        return bool(now and now.playing)

    def _idle_changed(self, show: bool) -> None:
        if self.link:
            self.link.set_idle(protocol.IDLE_FILE if show else None)

    # --- Game events ---------------------------------------------------------------------

    def client_log(self):
        """Client.txt: the configured path, else the simulator's test log, else the one found."""
        configured = self.store.settings["events"]["client_log"]
        if not configured and self.fake_log is not None:
            return self.fake_log
        return find_client_log(configured)

    def start_watcher(self) -> LogWatcher:
        self.watcher = LogWatcher(self.client_log, self.characters, self.on_game_event, on_line=self.maps.feed).start()
        self.maps.start(on_tick=self._map_tick)
        return self.watcher

    def _map_tick(self, changed: bool) -> None:
        """The map timer moved on: re-send the page shown if it has the current-map card, alone,
        so the timer ticks on the screen (the other pages wait for the next sync)."""
        page = self._shown_page() if changed and self.link else None
        if page is None or not any(slot and slot["widget"] == "current_map" for slot in page["slots"].values()):
            return
        data, _ = self.render_data()
        with self._render_lock:
            overlay = protocol.encode_overlay(renderer.overlay(page, data))
        self.link.refresh_page(PageContent(page["id"], overlay, {}))

    def _shown_page(self) -> dict | None:
        """The page on the screen, as it last said (the first one until it says)."""
        shown = pagelib.visible(self.store.pages)
        current = self.link.current_page if self.link else None
        return next((p for p in shown if p["id"] == current), shown[0] if shown else None)

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
        """Fetch new data now: WealthyExile when a cookie is saved (in the background), else one
        more demo point, timed now."""
        if self._can_fetch() and self._fetcher is not None:
            self.last_fetch = now
            self._fetch_now.set()  # the fetcher syncs WealthyExile first, then reads
            return
        self._demo_tick(now)
        src = self._demo_source
        src.sim_time = now - src.step  # fetch() steps forward, so the point lands exactly now
        self._demo_add(src.fetch())

    def demo_step(self, loot: int = 0) -> None:
        """One more demo point now, `loot` divines richer, on the screen: the demo command's
        moving values (stashdisplay demo). Without price noise, so the value climbs a few
        seconds apart instead of jumping up and down."""
        now = time.time()
        with self._data_lock:
            self._demo_tick(now)
            self._demo_source.noise = 0.0
            self._demo_source.qty["Divine Orb"] += loot
            self.refresh(now)
        self._screen_sync()

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
