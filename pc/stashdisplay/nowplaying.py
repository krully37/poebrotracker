"""What is playing on the PC, and the buttons to control it, for the media card.

On Windows this reads the system's own media session (the one behind the volume flyout):
Spotify, browsers, VLC and most players publish to it. Commands go through the same API,
never as simulated key presses. Elsewhere (the Mac, while developing) a fake player stands in.

A thread polls the session about once a second and calls `on_change` when what the card shows
changes (track, artist, cover, playing or paused). The playback position is not followed.
"""

import asyncio
import io
import logging
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

ACTIONS = ("media_prev", "media_toggle", "media_next")
POLL_SECONDS = 1.0
AFTER_COMMAND = (0.15, 0.4, 1.0)  # quick re-reads after a button, so the card follows at once


@dataclass(frozen=True)
class NowPlaying:
    title: str
    artist: str = ""
    app: str = ""  # the player's name, shown when there is no artist
    playing: bool = False
    can_prev: bool = True
    can_next: bool = True
    cover: bytes | None = None  # image file (JPEG or PNG) as the player gives it


class Player:
    """Base: holds the current state and runs the polling thread."""

    def __init__(self):
        self.on_change: Callable[[], None] = lambda: None
        self._now: NowPlaying | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="now-playing")

    def now(self) -> NowPlaying | None:
        with self._lock:
            return self._now

    def start(self) -> "Player":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()
        self._thread.join(timeout=2)

    def command(self, action: str) -> None:
        """Run a button (one of ACTIONS) on the player."""
        raise NotImplementedError

    def _set(self, now: NowPlaying | None) -> None:
        with self._lock:
            changed, self._now = now != self._now, now
        if changed:
            try:
                self.on_change()
            except Exception:
                log.exception("now playing listener failed")

    def _run(self) -> None:
        raise NotImplementedError


class FakePlayer(Player):
    """A pretend player for the Mac and the tests: a few tracks, play/pause, previous and next."""

    TRACKS = [
        ("The Twilight Strand", "Path of Exile soundtrack", "#6b3a1f"),
        ("Lioneye's Watch", "Path of Exile soundtrack", "#1f4a6b"),
        ("The Coast at Night, a much longer title that has to wrap", "Path of Exile soundtrack", "#3d5a2a"),
    ]

    def __init__(self):
        super().__init__()
        self.index = 0
        self.playing = True
        self._covers: dict[int, bytes] = {}
        self._publish()

    def command(self, action: str) -> None:
        if action == "media_toggle":
            self.playing = not self.playing
        elif action == "media_next":
            self.index = (self.index + 1) % len(self.TRACKS)
        elif action == "media_prev":
            self.index = (self.index - 1) % len(self.TRACKS)
        self._publish()

    def _publish(self) -> None:
        title, artist, _ = self.TRACKS[self.index]
        self._set(NowPlaying(title, artist, "Fake player", self.playing, cover=self._cover(self.index)))

    def _cover(self, index: int) -> bytes:
        if index not in self._covers:
            from PIL import Image, ImageDraw

            color = self.TRACKS[index][2]
            img = Image.new("RGB", (200, 200), color)
            d = ImageDraw.Draw(img)
            for r in range(90, 10, -16):
                d.ellipse((100 - r, 100 - r, 100 + r, 100 + r), outline="#d8b45a", width=3)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            self._covers[index] = buf.getvalue()
        return self._covers[index]

    def _run(self) -> None:
        pass  # nothing to poll: commands publish straight away


class WindowsPlayer(Player):
    """The Windows media session (GlobalSystemMediaTransportControlsSessionManager)."""

    def __init__(self):
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager = None
        self._cover_key: tuple | None = None
        self._cover: bytes | None = None

    def command(self, action: str) -> None:
        loop = self._loop
        if loop is None or action not in ACTIONS:
            return
        asyncio.run_coroutine_threadsafe(self._command(action), loop)

    async def _command(self, action: str) -> None:
        session = self._session()
        if session is None:
            return
        try:
            if action == "media_toggle":
                await session.try_toggle_play_pause_async()
            elif action == "media_next":
                await session.try_skip_next_async()
            else:
                await session.try_skip_previous_async()
        except OSError as e:
            log.info("media command %s failed: %s", action, e)
        for delay in AFTER_COMMAND:
            await asyncio.sleep(delay)
            await self._poll()

    def _session(self):
        return self._manager.get_current_session() if self._manager else None

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except Exception:
            log.exception("now playing stopped")

    async def _main(self) -> None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        self._manager = await Manager.request_async()
        while not self._stopped.is_set():
            try:
                await self._poll()
            except OSError as e:  # the player closed mid-read: next poll sees the new state
                log.debug("reading the media session failed: %s", e)
            await asyncio.sleep(POLL_SECONDS)

    async def _poll(self) -> None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status

        session = self._session()
        if session is None:
            self._set(None)
            return
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        if not props or not (props.title or props.artist):
            self._set(None)
            return
        key = (session.source_app_user_model_id, props.title, props.artist, props.album_title)
        if key != self._cover_key:
            self._cover_key, self._cover = key, await _read_cover(props.thumbnail)
        controls = info.controls
        self._set(NowPlaying(
            title=props.title or "",
            artist=props.artist or "",
            app=app_name(session.source_app_user_model_id or ""),
            playing=info.playback_status == Status.PLAYING,
            can_prev=bool(controls.is_previous_enabled),
            can_next=bool(controls.is_next_enabled),
            cover=self._cover,
        ))


async def _read_cover(thumbnail) -> bytes | None:
    if thumbnail is None:
        return None
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

    try:
        stream = await thumbnail.open_read_async()
        buf = Buffer(stream.size)
        await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
        data = bytearray(buf.length)
        DataReader.from_buffer(buf).read_bytes(data)
        return bytes(data)
    except OSError as e:
        log.debug("reading the cover failed: %s", e)
        return None


def app_name(app_id: str) -> str:
    """'Spotify.exe' -> 'Spotify'; packaged apps ('Microsoft.ZuneMusic_8wekyb3d8bbwe!App') -> 'ZuneMusic'."""
    name = app_id.split("!")[0].split("\\")[-1]
    name = name.removesuffix(".exe").removesuffix(".EXE")
    if "_" in name:
        name = name.split("_")[0]
    name = name.split(".")[-1] if "." in name else name
    # Firefox and its forks register under a hash ("6F940AC27A98DD61"): no name worth showing.
    return "" if len(name) >= 12 and all(c in "0123456789abcdefABCDEF" for c in name) else name


def create_player(fake: bool = False) -> Player:
    """The real player on Windows (when its packages are there), else the fake one."""
    if not fake and sys.platform == "win32":
        try:
            import winrt.windows.media.control  # noqa: F401

            return WindowsPlayer()
        except ImportError:
            log.warning("Windows media packages missing: the media card uses a fake player")
    return FakePlayer()
