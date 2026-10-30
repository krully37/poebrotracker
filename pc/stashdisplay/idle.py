"""Whether the PC is in use, for the screen's idle cat.

Windows keeps the time of the last keyboard or mouse input (the same clock its own screen
saver uses), and the app reads it once a second. Nothing is hooked and the game is not
touched. The cat shows after the configured minutes without input, but not while music or
a video plays, and not for a minute after someone touches the screen to see the pages.
"""

import ctypes
import logging
import sys
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

POLL = 1.0  # seconds between checks
WAKE_SECONDS = 60  # a touch on the cat shows the pages this long, then the cat comes back


def input_idle_seconds() -> float | None:
    """Seconds since the last keyboard or mouse input, or None where that is unknown (not Windows)."""
    if sys.platform != "win32":
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000  # both are 32-bit ms counters that wrap


class IdleWatch:
    """Calls on_change(True) when the cat should show, and on_change(False) when it should go."""

    def __init__(self, settings: Callable[[], dict], media_playing: Callable[[], bool],
                 on_change: Callable[[bool], None], idle_seconds: Callable[[], float | None] = input_idle_seconds,
                 clock: Callable[[], float] = time.monotonic):
        self.settings = settings  # the "idle" settings: {"enabled", "minutes"}
        self.media_playing = media_playing
        self.on_change = on_change
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.forced = False  # the simulator page's "Pretend the PC is idle"
        self.active = False
        self._woken_until = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="idle-watch")

    def start(self) -> "IdleWatch":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def wake(self) -> None:
        """Someone touched the screen: the pages for a minute."""
        self._woken_until = self.clock() + WAKE_SECONDS
        self.check()

    def pretend(self, idle: bool) -> None:
        """Show the cat now, or stop pretending (the demo command), whatever a touch said before."""
        self.forced = idle
        self._woken_until = 0.0
        self.check()

    def should_show(self) -> bool:
        s = self.settings()
        if not s["enabled"] or self.clock() < self._woken_until or self.media_playing():
            return False
        if self.forced:
            return True
        idle = self.idle_seconds()
        return idle is not None and idle >= s["minutes"] * 60

    def check(self) -> None:
        show = self.should_show()
        if show != self.active:
            self.active = show
            try:
                self.on_change(show)
            except Exception:
                log.exception("idle listener failed")

    def _run(self) -> None:
        while not self._stop.wait(POLL):
            self.check()
