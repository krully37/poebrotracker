"""Tray icon: the app's only window. Right-click for the menu; a click opens the settings."""

import logging
import webbrowser

from PIL import Image, ImageDraw

from . import autostart
from .app import App
from .web import server

log = logging.getLogger(__name__)

STATUS = {
    "disconnected": "Screen not connected",
    "connected": "Screen connected",
}


def icon_image(size: int = 64) -> Image.Image:
    """A gold orb on a dark disc, readable at 16 px."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((1, 1, size - 2, size - 2), fill=(21, 17, 12, 255), outline=(140, 118, 80, 255), width=max(1, size // 16))
    c, r = size / 2, size * 0.26
    d.ellipse((c - r, c - r, c + r, c + r), fill=(201, 162, 74, 255))
    hl = r * 0.4
    d.ellipse((c - r * 0.55, c - r * 0.6, c - r * 0.55 + hl, c - r * 0.6 + hl), fill=(240, 222, 170, 255))
    return img


def open_settings(app: App) -> None:
    webbrowser.open(server.url(app))


def run(app: App, web_server) -> None:
    """Show the tray icon until Quit. Blocks; must run on the main thread (macOS requires it)."""
    import pystray

    def status_text(_item) -> str:
        return STATUS.get(app.status["screen"], app.status["screen"])

    def toggle_autostart(icon, _item) -> None:
        autostart.set_enabled(not autostart.enabled())
        icon.update_menu()

    def quit_app(icon, _item) -> None:
        icon.stop()
        web_server.close()

    menu = pystray.Menu(
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open settings", lambda: open_settings(app), default=True),
        pystray.MenuItem(
            "Start with Windows", toggle_autostart,
            checked=lambda _item: autostart.enabled(), visible=autostart.supported(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    pystray.Icon("stashdisplay", icon_image(), "Stash Display", menu).run()
