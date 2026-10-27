"""The running app: settings, assets, media and the data shown on the pages.

The settings page and the tray both talk to one App. Later steps plug in the
WealthyExile fetch loop (which sets `live_data`) and the screen link (which
listens to `on_save`).
"""

import dataclasses
import io
import logging
import threading
import time
from collections.abc import Callable

from . import paths
from .assets import AssetCache
from .media import MediaStore
from .render import data as renderdata
from .render import fonts, renderer
from .settings import Store

log = logging.getLogger(__name__)

DEMO_MAX_AGE = 60


class App:
    def __init__(self, store: Store, assets: AssetCache, media: MediaStore):
        self.store = store
        self.assets = assets
        self.media = media
        self.live_data: renderdata.RenderData | None = None
        self.status = {"screen": "disconnected", "last_sync": None, "error": None}
        self.on_save: list[Callable[[], None]] = []
        self._render_lock = threading.Lock()  # Pillow fonts are not safe to share across threads
        self._demo: tuple[float, renderdata.RenderData] | None = None

    @classmethod
    def create(cls, offline: bool = False) -> "App":
        store = Store.load(paths.settings_path())
        assets = AssetCache(offline=offline)
        app = cls(store, assets, MediaStore(paths.app_dir() / "media"))
        fonts.register_fontin(assets.fontin())
        return app

    def render_data(self, force_demo: bool = False) -> tuple[renderdata.RenderData, bool]:
        """Data for a render, and whether it is demo data."""
        now = time.time()
        if self.live_data is not None and not force_demo:
            return dataclasses.replace(self.live_data, now=now), False
        if self._demo is None or now - self._demo[0] > DEMO_MAX_AGE:
            from .cli import demo_render_data  # import here: cli imports this module
            self._demo = (now, demo_render_data(now, seed=7, assets=self.assets))
        return dataclasses.replace(self._demo[1], now=now, synced_at=now - 130), True

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
