"""The PC end of the link: finds the screen, keeps it in sync, and passes touch events back.

One thread owns the port. It sends one frame at a time and waits for its ACK (resending on
timeout), so a lost byte costs a resend, never a wrong picture. After a reconnect the screen
says what it already holds, and only what changed is sent again.
"""

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import protocol as p
from .transport import Port

log = logging.getLogger(__name__)

RETRY_CONNECT = 2.0  # seconds between attempts to find the screen
RESYNC_EVERY = 60  # pages are re-rendered every minute (clock, "synced X ago")
ANIM_PREFIX = "anim-"  # event animations (game start, level-up, death)


class LinkError(Exception):
    pass


@dataclass
class PageContent:
    id: str
    overlay: bytes  # encoded overlay (protocol.encode_overlay)
    bg: dict  # {"color": "#rrggbb"} or {"file": id, "color": fallback}
    zones: list[dict] = field(default_factory=list)

    @property
    def crc(self) -> str:
        return p.crc_hex(self.overlay)


@dataclass
class FileContent:
    data: bytes
    format: str  # "jpeg", "gif" or "sprite" (later "mjpeg")
    over_page: bool = False  # an event GIF with see-through pixels, played over the current page

    @property
    def crc(self) -> str:
        return p.crc_hex(self.data)


@dataclass
class Content:
    pages: list[PageContent]
    files: dict[str, FileContent]
    # Other overlays the screen keeps, by id (starting with "@"): the reset banners.
    overlays: dict[str, bytes] = field(default_factory=dict)


class ScreenLink:
    def __init__(self, ports: Callable[[], Iterable[Port]], content: Callable[[], Content],
                 on_event: Callable[[dict], None], clock: Callable[[], float] = time.monotonic,
                 on_connect: Callable[[dict], None] | None = None):
        self.ports = ports
        self.content = content
        self.on_event = on_event
        self.on_connect = on_connect  # after the first sync of each connection, with the inventory
        self.clock = clock
        self.state = "searching"
        self.info: dict = {}
        self.jobs: queue.Queue = queue.Queue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="screen-link")
        self.port: Port | None = None
        self.reader = p.FrameReader()
        self.seq = 0
        self.xfer = 0
        self.inventory: dict = {}
        self.last_sent = 0.0
        self.last_sync = 0.0
        self.seen_events: list[int] = []
        self.current_page: str | None = None
        self.idle_sprite: str | None = None  # the PC is idle: the screen bounces this file

    # --- Public API (any thread) ---------------------------------------------------------

    def start(self) -> "ScreenLink":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=3)

    def request_sync(self) -> None:
        self.jobs.put(("sync",))

    def refresh_page(self, page: PageContent) -> None:
        """Send one page's new overlay now, without a whole sync: the map timer ticking on the
        page shown. The screen swaps it in as it arrives; the next sync lists its new crc."""
        if self.state != "searching":
            self.jobs.put(("page", page))

    def toast(self, overlay: bytes, seconds: float = 2.0) -> None:
        self.jobs.put(("toast", overlay, seconds))

    def play(self, file_id: str | None, overlay: bytes | None, seconds: float, over_page: bool = False) -> bool:
        """Play an event animation now. Dropped (False) while the screen is away: old news by then."""
        if self.state == "searching":
            return False
        self.jobs.put(("play", file_id, overlay, seconds, over_page))
        return True

    def set_idle(self, sprite: str | None) -> None:
        """Show the idle cat (a sprite file id), or the pages again (None). Kept across reconnects."""
        self.idle_sprite = sprite
        self.jobs.put(("idle",))

    def has_file(self, file_id: str) -> bool:
        return self.state != "searching" and file_id in self.inventory.get("files", {})

    # --- Connection ------------------------------------------------------------------------

    def _run(self) -> None:
        while not self.stopped.is_set():
            port = self._connect()
            if port is None:
                self.stopped.wait(RETRY_CONNECT)
                continue
            try:
                self._session()
            except (OSError, LinkError) as e:
                log.info("screen link lost: %s", e)
                self.info["error"] = str(e)
            finally:
                port.close()
                self.port = None
                self.state = "searching"
            self.stopped.wait(RETRY_CONNECT)

    def _connect(self) -> Port | None:
        try:
            candidates = list(self.ports())
        except OSError as e:
            log.debug("listing ports failed: %s", e)
            return None
        for port in candidates:
            self.port, self.reader = port, p.FrameReader()
            try:
                self.inventory = self._request(p.HELLO, {"version": p.VERSION, "time": int(time.time())}, retries=1)
            except (OSError, LinkError):
                port.close()
                continue
            if self.inventory.get("version") != p.VERSION:
                log.warning("screen speaks protocol %s, we speak %s", self.inventory.get("version"), p.VERSION)
            self.state = "connected"
            self.info = {"port": port.name, "firmware": self.inventory.get("firmware"),
                         "flash_total": self.inventory.get("flash_total"),
                         "flash_free": self.inventory.get("flash_free"), "error": None}
            log.info("screen found on %s (%s)", port.name, self.info["firmware"])
            return port
        self.port = None
        return None

    def _session(self) -> None:
        self._sync()
        if self.on_connect:
            try:
                self.on_connect(self.inventory)
            except Exception:
                log.exception("screen connect handler failed")
        if self.idle_sprite:
            self._send_idle()  # a new connection starts on the pages
        while not self.stopped.is_set():
            try:
                job = self.jobs.get(timeout=0.1)
            except queue.Empty:
                job = None
            if job:
                self._do(job)
            self._read_frames(0.0)
            now = self.clock()
            if now - self.last_sync >= RESYNC_EVERY:
                self._sync()
            elif now - self.last_sent >= p.HEARTBEAT:
                self._request(p.PING, {})

    def _do(self, job: tuple) -> None:
        kind = job[0]
        if kind == "sync":
            while not self.jobs.empty() and self.jobs.queue[0][0] == "sync":
                self.jobs.get_nowait()  # several saves in a row need one sync
            self._sync()
        elif kind == "page":
            page = job[1]
            have = self.inventory.setdefault("overlays", {})
            if page.id in have and have[page.id] != page.crc:  # only a page the screen already holds
                self._transfer("overlay", page.id, page.overlay)
                have[page.id] = page.crc
        elif kind == "toast":
            self._transfer("toast", "@toast", job[1], seconds=job[2])
        elif kind == "play":
            _, file_id, overlay, seconds, over_page = job
            if overlay is not None:
                self._transfer("overlay", "@event", overlay)
            msg = {"file": file_id, "overlay": "@event" if overlay else None, "seconds": seconds}
            if over_page:
                msg["over_page"] = True
            self._request(p.PLAY, msg)
        elif kind == "idle":
            self._send_idle()

    def _send_idle(self) -> None:
        sprite = self.idle_sprite
        # Not on the screen (no room for it): the pages stay.
        self._request(p.IDLE, {"sprite": sprite if sprite and self.has_file(sprite) else None})

    # --- Sync --------------------------------------------------------------------------------

    def _sync(self) -> None:
        self.state = "syncing"
        content = self.content()
        have_files = self.inventory.setdefault("files", {})
        have_overlays = self.inventory.setdefault("overlays", {})
        # Free space first, then backgrounds, overlays (the page on screen first), the page list, animations.
        for file_id in list(have_files):
            if file_id not in content.files:
                reply = self._request(p.DELETE, {"id": file_id})
                have_files.pop(file_id, None)
                self.info["flash_free"] = reply.get("flash_free", self.info.get("flash_free"))
        # Backgrounds before the pages that use them; animations last, so pages show up first.
        backgrounds = {k: f for k, f in content.files.items() if not _is_animation(k)}
        anims = {k: f for k, f in content.files.items() if _is_animation(k)}
        missing_files = self._upload(backgrounds, have_files)
        pages = sorted(content.pages, key=lambda pg: pg.id != self.current_page)
        for page in pages:
            if have_overlays.get(page.id) != page.crc:
                self._transfer("overlay", page.id, page.overlay)
                have_overlays[page.id] = page.crc
        self._request(p.PAGES, {"pages": [
            {"id": pg.id, "overlay": pg.crc, "zones": pg.zones,
             "bg": {"color": pg.bg.get("color", "#000000")} if pg.bg.get("file") in missing_files else pg.bg}
            for pg in content.pages
        ]})
        for overlay_id, blob in content.overlays.items():
            if have_overlays.get(overlay_id) != p.crc_hex(blob):
                self._transfer("overlay", overlay_id, blob)
                have_overlays[overlay_id] = p.crc_hex(blob)
        keep = {pg.id for pg in content.pages} | set(content.overlays)
        for stale in [k for k in have_overlays if k not in keep]:
            del have_overlays[stale]
        missing_files |= self._upload(anims, have_files)
        self.info["error"] = "Not enough space on the screen for every background and animation" if missing_files else None
        self.last_sync = self.clock()
        self.info["last_sync"] = time.time()
        self.state = "connected"

    def _upload(self, files: dict[str, FileContent], have_files: dict) -> set[str]:
        """Send the files the screen lacks. Returns the ids that did not fit."""
        missing = set()
        for file_id, f in files.items():
            if have_files.get(file_id, {}).get("crc") == f.crc:
                continue
            try:
                self._transfer("file", file_id, f.data, format=f.format)
                have_files[file_id] = {"crc": f.crc, "size": len(f.data), "format": f.format}
            except NoSpace:
                missing.add(file_id)
        return missing

    def _transfer(self, kind: str, blob_id: str, data: bytes, **meta) -> None:
        for _attempt in range(2):
            self.xfer = (self.xfer + 1) & 0xFFFF
            begin = self._request(p.BEGIN, {"xfer": self.xfer, "kind": kind, "id": blob_id, "size": len(data),
                                            "crc": p.crc_hex(data), **meta})
            if not begin.get("ok"):
                if begin.get("error") == "no_space":
                    raise NoSpace(blob_id)
                raise LinkError(f"BEGIN refused: {begin.get('error')}")
            ok = True
            for offset in range(0, len(data), p.MAX_CHUNK):
                reply = self._request(p.CHUNK, payload=p.chunk_payload(self.xfer, offset, data[offset:offset + p.MAX_CHUNK]))
                if not reply.get("ok"):
                    ok = False
                    break
            if ok:
                end = self._request(p.END, {"xfer": self.xfer})
                if end.get("ok"):
                    if "flash_free" in end:
                        self.info["flash_free"] = end["flash_free"]
                    return
        raise LinkError(f"transfer of {blob_id} failed twice")

    # --- Frames ------------------------------------------------------------------------------

    def _request(self, frame_type: int, obj: dict | None = None, payload: bytes | None = None,
                 retries: int = p.RETRIES) -> dict:
        """Send one frame and wait for its ACK, resending on timeout."""
        assert self.port is not None
        self.seq = (self.seq + 1) & 0xFFFF
        raw = p.encode_frame(frame_type, self.seq, payload) if payload is not None else p.json_frame(frame_type, self.seq, obj)
        for _ in range(retries):
            self.port.write(raw)
            self.last_sent = self.clock()
            deadline = self.clock() + p.ACK_TIMEOUT
            while self.clock() < deadline:
                for frame in self._read_frames(max(0.0, deadline - self.clock())):
                    if frame.type == p.ACK and frame.seq == self.seq:
                        return frame.json()
        raise LinkError(f"no answer to {p.NAMES.get(frame_type)}")

    def _read_frames(self, timeout: float) -> list[p.Frame]:
        """Frames waiting on the port. Events are answered and handled here; ACKs are returned."""
        assert self.port is not None
        acks = []
        for frame in self.reader.feed(self.port.read(timeout)):
            if frame.type == p.ACK:
                acks.append(frame)
            elif frame.type == p.EVENT:
                self.port.write(p.encode_frame(p.EVENT_ACK, frame.seq))
                if frame.seq in self.seen_events:
                    continue  # a resend: our EVENT_ACK got lost
                self.seen_events = (self.seen_events + [frame.seq])[-32:]
                try:
                    event = frame.json()
                except p.ProtocolError:
                    continue
                if event.get("type") == "page":
                    self.current_page = event.get("page")
                try:
                    self.on_event(event)
                except Exception:
                    log.exception("screen event handler failed")
            elif frame.type == p.LOG:
                log.info("screen: %s", frame.payload.decode("utf-8", "replace"))
        return acks


class NoSpace(LinkError):
    pass


def _is_animation(file_id: str) -> bool:
    return file_id.startswith(ANIM_PREFIX) or file_id in (p.BOOT_FILE, p.IDLE_FILE)
