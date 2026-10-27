"""The running app: settings, assets, media, history, the data shown on the pages, and the screen.

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
from .link import protocol
from .link.client import Content, ScreenLink
from .link.content import ContentBuilder
from .link.transport import Port, SerialPort, candidate_ports
from .media import MediaStore
from .render import data as renderdata
from .render import fonts, renderer
from .settings import Store

log = logging.getLogger(__name__)

TOASTS = {"reset_session": "Session reset", "reset_rate": "Div/h reset"}


class App:
    def __init__(self, store: Store, assets: AssetCache, media: MediaStore):
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

    @classmethod
    def create(cls, offline: bool = False) -> "App":
        store = Store.load(paths.settings_path())
        assets = AssetCache(offline=offline)
        app = cls(store, assets, MediaStore(paths.app_dir() / "media"))
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
        if self.live_data is not None and not force_demo:
            return dataclasses.replace(self.live_data, now=now), False
        with self._data_lock:
            self._demo_tick(now)
            snap = self.last_snapshot
            s = self.store.settings
            data = renderdata.build(
                self.history, snap, now=now, synced_at=snap.time, item_prices=demo_prices(snap.div_price),
                spark_points=s["spark_points"], rate_window=s["rate_window_minutes"] * 60, icon=self.assets.icon,
            )
        return data, True

    # --- Screen ---------------------------------------------------------------------------

    def start_link(self, ports: Callable[[], list[Port]] | None = None) -> ScreenLink:
        """Connect to the screen: the given ports (the simulator), else USB serial ports."""
        self.link = ScreenLink(ports or self._serial_ports, self.screen_content, self.on_screen_event).start()
        return self.link

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
            return self.content.build(self.store.pages, data)

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
