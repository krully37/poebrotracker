"""A simulated screen: does what the firmware will do, so the PC side can be built and tested
before the hardware arrives. The settings page shows it at /simulator.

It keeps the same state as the firmware: page overlays in "PSRAM" (lost on power cycle),
files in "flash" (kept), the current page, touch gestures, the offline timer, and the idle cat.
"""

import io
import math
import random
import threading
import time
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageEnhance

from ..render import renderer
from ..render.theme import GOLD, HEIGHT, HOLD_BAR, WIDTH
from . import protocol as p
from .transport import Port

FIRMWARE = "sim-1"


class SimScreen:
    def __init__(self, port: Port | None = None, clock: Callable[[], float] = time.monotonic,
                 flash_bytes: int = p.FLASH_BYTES):
        self.port = port
        self.clock = clock
        self.flash_bytes = flash_bytes
        self.files: dict[str, dict] = {}  # flash: survives power cycles
        self.lock = threading.RLock()
        self.reader = p.FrameReader()
        self.power_cycle()

    # --- Power and storage ----------------------------------------------------------

    def power_cycle(self) -> None:
        with self.lock:
            self.pages: list[dict] = []
            self.overlays: dict[str, tuple[str, bytes]] = {}  # id -> (crc, blob)
            self.xfers: dict[int, dict] = {}
            self.current = 0
            self.last_rx: float | None = None
            self.last_reply: tuple[int, int, bytes] | None = None  # (type, seq, frame) for resends
            self.slide: tuple[int, int, float] | None = None  # (from, to, start)
            self.toast: tuple[str, float] | None = None  # (overlay id, until)
            # (file, overlay, start, until, over the page)
            self.anim: tuple[str | None, str | None, float, float, bool] | None = None
            self.touch: dict | None = None
            self.idle: dict | None = None  # the bouncing cat while the PC is idle
            self.event_seq = 0
            self.pending_events: dict[int, tuple[bytes, float, int]] = {}  # seq -> (frame, sent, tries)
            self.decoded: dict[str, Image.Image] = {}
            boot = self.files.get(p.BOOT_FILE)
            if boot:
                self.anim = (p.BOOT_FILE, None, self.clock(), self.clock() + _duration(boot), False)

    def flash_used(self) -> int:
        return sum(f["size"] for f in self.files.values())

    def inventory(self) -> dict:
        return {
            "ok": True, "version": p.VERSION, "firmware": FIRMWARE, "width": WIDTH, "height": HEIGHT,
            "flash_total": self.flash_bytes, "flash_free": self.flash_bytes - self.flash_used(),
            "overlays": {k: crc for k, (crc, _) in self.overlays.items()},
            "files": {k: {"crc": f["crc"], "size": f["size"], "format": f["format"]} for k, f in self.files.items()},
            "playing": self.anim[0] if self.anim and self.clock() < self.anim[3] else None,
        }

    # --- Wire -----------------------------------------------------------------------------

    def poll(self, timeout: float = 0.05) -> None:
        """Read what the PC sent and run timers. The firmware's main loop does the same."""
        try:
            data = self.port.read(timeout) if self.port else b""
        except OSError:  # cable pulled: the screen just stops hearing from the PC
            data = b""
            time.sleep(timeout)
        if data:
            for frame in self.reader.feed(data):
                self.handle(frame)
        self.tick()

    def send(self, raw: bytes) -> None:
        if self.port:
            try:
                self.port.write(raw)
            except OSError:
                pass

    def handle(self, frame: p.Frame) -> None:
        with self.lock:
            now = self.clock()
            self.last_rx = now
            if frame.type == p.EVENT_ACK:
                self.pending_events.pop(frame.seq, None)
                return
            if self.last_reply and self.last_reply[:2] == (frame.type, frame.seq):
                self.send(self.last_reply[2])  # the PC missed our ACK: same answer again
                return
            try:
                reply = self._apply(frame, now)
            except (p.ProtocolError, KeyError, TypeError, ValueError) as e:
                reply = {"ok": False, "error": str(e) or type(e).__name__}
            raw = p.json_frame(p.ACK, frame.seq, reply)
            self.last_reply = (frame.type, frame.seq, raw)
            self.send(raw)

    def _apply(self, frame: p.Frame, now: float) -> dict:
        t = frame.type
        if t == p.CHUNK:
            xfer_id, offset, data = p.parse_chunk(frame.payload)
            xfer = self.xfers[xfer_id]
            if offset != len(xfer["buf"]):
                return {"ok": False, "error": "offset", "have": len(xfer["buf"])}
            if offset + len(data) > xfer["size"]:
                return {"ok": False, "error": "too_long"}
            xfer["buf"] += data
            return {"ok": True}
        msg = frame.json()
        if t == p.HELLO:
            self.xfers.clear()
            self.idle = None  # a new connection starts on the pages
            return self.inventory()
        if t == p.PING:
            return {"ok": True}
        if t == p.PAGES:
            return self._set_pages(msg["pages"])
        if t == p.BEGIN:
            return self._begin(msg)
        if t == p.END:
            return self._end(self.xfers.pop(msg["xfer"]), now)
        if t == p.DELETE:
            self.files.pop(msg["id"], None)
            self.decoded.pop("file:" + msg["id"], None)
            if self.idle and self.idle["sprite"] == msg["id"]:
                self.idle = None
            return {"ok": True, "flash_free": self.flash_bytes - self.flash_used()}
        if t == p.PLAY:
            seconds = float(msg.get("seconds", 4))
            self.anim = (msg.get("file"), msg.get("overlay"), now, now + seconds, bool(msg.get("over_page")))
            return {"ok": True}
        if t == p.IDLE:
            return self._set_idle(msg.get("sprite"), now)
        return {"ok": False, "error": "unknown_type"}

    def _set_pages(self, pages: list[dict]) -> dict:
        current_id = self.pages[self.current]["id"] if self.pages else None
        self.pages = [pg for pg in pages if isinstance(pg, dict) and pg.get("id")]
        ids = {pg["id"] for pg in self.pages}
        for stale in [k for k in self.overlays if k not in ids and not k.startswith("@")]:
            del self.overlays[stale]
        order = [pg["id"] for pg in self.pages]
        self.current = order.index(current_id) if current_id in order else 0
        self.slide = None
        return {"ok": True}

    def _set_idle(self, sprite: str | None, now: float) -> dict:
        if sprite is None:
            self.idle = None
            return {"ok": True}
        f = self.files.get(sprite)
        if f is None or f["format"] != "sprite":
            return {"ok": False, "error": "no_file"}
        if self.idle and self.idle["sprite"] == sprite:
            return {"ok": True}  # already bouncing: carry on from where it is
        # From the middle, in a random diagonal direction, already facing it.
        heading = math.radians(random.uniform(20, 70) + 90 * random.randrange(4))
        vx, vy = p.IDLE_SPEED * math.cos(heading), p.IDLE_SPEED * math.sin(heading)
        self.idle = {"sprite": sprite, "x": WIDTH / 2, "y": HEIGHT / 2, "vx": vx, "vy": vy,
                     "angle": _facing(vx, vy), "t": now, "turned": None}
        return {"ok": True}

    def _begin(self, msg: dict) -> dict:
        kind, size = msg["kind"], int(msg["size"])
        if kind not in ("overlay", "file", "toast"):
            return {"ok": False, "error": "kind"}
        if kind == "file":
            replaced = self.files.get(msg["id"], {}).get("size", 0)
            if size > self.flash_bytes - self.flash_used() + replaced:
                return {"ok": False, "error": "no_space", "flash_free": self.flash_bytes - self.flash_used()}
        self.xfers[int(msg["xfer"])] = {**msg, "size": size, "buf": bytearray()}
        return {"ok": True}

    def _end(self, xfer: dict, now: float) -> dict:
        blob = bytes(xfer["buf"])
        if len(blob) != xfer["size"] or p.crc_hex(blob) != xfer["crc"]:
            return {"ok": False, "error": "crc"}
        if xfer["kind"] == "file":
            self.files[xfer["id"]] = {"data": blob, "crc": xfer["crc"], "size": len(blob),
                                      "format": xfer.get("format", "jpeg")}
            self.decoded.pop("file:" + xfer["id"], None)
            if self.idle and self.idle["sprite"] == xfer["id"]:
                self.idle["turned"] = None  # a new cat: turn the new one
            return {"ok": True, "flash_free": self.flash_bytes - self.flash_used()}
        p.decode_overlay(blob)  # reject garbage now rather than at draw time
        self.overlays[xfer["id"]] = (xfer["crc"], blob)
        self.decoded.pop("ov:" + xfer["id"], None)
        if xfer["kind"] == "toast":
            self.toast = (xfer["id"], now + float(xfer.get("seconds", 2)))
        return {"ok": True}

    # --- Events to the PC ---------------------------------------------------------------

    def _event(self, obj: dict) -> None:
        self.event_seq = (self.event_seq + 1) & 0xFFFF
        raw = p.json_frame(p.EVENT, self.event_seq, obj)
        if self.online(self.clock()):
            self.pending_events[self.event_seq] = (raw, self.clock(), 1)
            self.send(raw)
        # Offline: dropped. Nobody is there to answer a tap or a reset.

    def tick(self) -> None:
        with self.lock:
            now = self.clock()
            for seq, (raw, sent, tries) in list(self.pending_events.items()):
                if now - sent >= p.ACK_TIMEOUT:
                    if tries >= p.RETRIES or not self.online(now):
                        del self.pending_events[seq]
                    else:
                        self.pending_events[seq] = (raw, now, tries + 1)
                        self.send(raw)
            if self.idle:
                if self.online(now):
                    self._idle_step(now)
                else:
                    self.idle = None  # the PC went away: the offline screen, as always
            touch = self.touch
            if touch and not touch["moved"] and not touch["done"] and self.pages:
                held = now - touch["t0"]
                if _holds(touch["zone"]) and held >= p.PRESS_DELAY + p.HOLD_FILL:
                    touch["done"] = True
                    self._event({"type": "reset", "action": touch["zone"]["action"], "page": self._page_id()})
            if self.slide and now - self.slide[2] >= p.SLIDE_SECONDS:
                self.slide = None
            if self.toast and now >= self.toast[1]:
                self.toast = None
            if self.anim and now >= self.anim[3]:
                self.anim = None

    def _idle_step(self, now: float) -> None:
        """Move the cat, turn it towards where it goes, and bounce it off the edges of what shows."""
        st = self.idle
        dt, st["t"] = min(0.1, now - st["t"]), now
        if dt <= 0:
            return
        turn = (_facing(st["vx"], st["vy"]) - st["angle"] + 180) % 360 - 180
        st["angle"] += turn * (1 - math.exp(-dt / p.IDLE_TURN))
        left, top, right, bottom = self._idle_extents()
        st["x"] += st["vx"] * dt
        st["y"] += st["vy"] * dt
        if (st["x"] - left < 0 and st["vx"] < 0) or (st["x"] + right > WIDTH and st["vx"] > 0):
            st["vx"] = -st["vx"]
        if (st["y"] - top < 0 and st["vy"] < 0) or (st["y"] + bottom > HEIGHT and st["vy"] > 0):
            st["vy"] = -st["vy"]
        # Turning changes its outline: keep all of it on the screen.
        st["x"] = min(max(st["x"], left), WIDTH - right)
        st["y"] = min(max(st["y"], top), HEIGHT - bottom)

    def _idle_turned(self) -> Image.Image:
        """The sprite turned to its current angle (to the nearest degree, like the firmware)."""
        st = self.idle
        angle = round(st["angle"]) % 360
        if st["turned"] is None or st["turned"][0] != angle:
            key = "sprite:" + self.files[st["sprite"]]["crc"]  # a new sprite under the same id decodes again
            if key not in self.decoded:
                self.decoded[key] = p.decode_overlay(self.files[st["sprite"]]["data"])
            st["turned"] = (angle, self.decoded[key].rotate(angle, Image.Resampling.BICUBIC, expand=True))
        return st["turned"][1]

    def _idle_extents(self) -> tuple[float, float, float, float]:
        """How far the visible cat reaches left, up, right and down from its centre."""
        img = self._idle_turned()
        x0, y0, x1, y1 = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
        return img.width / 2 - x0, img.height / 2 - y0, x1 - img.width / 2, y1 - img.height / 2

    def _idle_frame(self) -> Image.Image:
        img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
        cat = self._idle_turned()
        img.alpha_composite(cat, (round(self.idle["x"] - cat.width / 2), round(self.idle["y"] - cat.height / 2)))
        return img.convert("RGB")

    def online(self, now: float) -> bool:
        return self.last_rx is not None and now - self.last_rx < p.OFFLINE_AFTER

    def _page_id(self) -> str | None:
        return self.pages[self.current]["id"] if self.pages else None

    # --- Touch ---------------------------------------------------------------------------

    def touch_down(self, x: float, y: float) -> None:
        with self.lock:
            wake = self.idle is not None and self.anim is None
            zone = None if wake else self._zone_at(x, y)
            self.touch = {"t0": self.clock(), "x0": x, "y0": y, "x": x, "y": y,
                          "moved": False, "done": False, "zone": zone, "wake": wake}

    def touch_move(self, x: float, y: float) -> None:
        with self.lock:
            t = self.touch
            if not t:
                return
            t["x"], t["y"] = x, y
            if abs(x - t["x0"]) > p.TOUCH_SLOP or abs(y - t["y0"]) > p.TOUCH_SLOP:
                t["moved"] = True  # also cancels a ring in progress

    def touch_up(self, x: float, y: float) -> None:
        with self.lock:
            self.touch_move(x, y)
            t, self.touch = self.touch, None
            if t and t["wake"]:
                # Any touch on the cat brings the pages back; the PC keeps the cat away for a while.
                self.idle = None
                self._event({"type": "wake", "page": self._page_id()})
                return
            if not t or t["done"] or not self.pages:
                return
            now = self.clock()
            dx, dy = x - t["x0"], y - t["y0"]
            if t["moved"]:
                if abs(dx) >= p.SWIPE_MIN and abs(dx) > abs(dy) and len(self.pages) > 1:
                    old = self.current
                    self.current = (self.current + (1 if dx < 0 else -1)) % len(self.pages)
                    self.slide = (old, self.current, now)
                    self._event({"type": "page", "page": self._page_id()})
            elif now - t["t0"] < p.PRESS_DELAY:
                zone = t["zone"]
                if zone and zone.get("gesture") == "tap":
                    self._event({"type": "tap", "page": self._page_id(), "action": zone["action"]})
                else:
                    self._event({"type": "tap", "page": self._page_id()})
            # Held without a zone, or let go before the ring closed: nothing.

    def _zone_at(self, x: float, y: float) -> dict | None:
        if not self.pages:
            return None
        for z in self.pages[self.current].get("zones", []):
            if z["x"] <= x < z["x"] + z["w"] and z["y"] <= y < z["y"] + z["h"]:
                return z
        return None

    # --- Drawing ---------------------------------------------------------------------------

    def frame(self) -> Image.Image:
        """What the panel shows right now."""
        with self.lock:
            now = self.clock()
            if self.anim:
                file_id, overlay_id, start, _, over_page = self.anim
                if over_page and self.pages:
                    # The page as it was, dimmed; the GIF's see-through pixels show it.
                    img = self._page_image(self.current, now).convert("RGBA")
                    renderer.dots(img, self.current, len(self.pages))
                    img = ImageEnhance.Brightness(img.convert("RGB")).enhance(p.EVENT_DIM)
                else:
                    img = Image.new("RGB", (WIDTH, HEIGHT))
                if file_id:
                    img = _over(img, self._file_frame(file_id, now - start))
                img = self._with_overlay(img, overlay_id)
                return img if self.online(now) or file_id == "boot" else _dim(img)
            if not self.online(now) or not self.pages:
                return _dim(offline_screen(self.last_rx is not None))
            if self.idle:
                return self._idle_frame()
            if self.slide:
                old, new, start = self.slide
                progress = _ease(min(1.0, (now - start) / p.SLIDE_SECONDS))
                forward = (new - old) % len(self.pages) == 1
                shift = int(WIDTH * progress) * (1 if forward else -1)
                img = Image.new("RGB", (WIDTH, HEIGHT))
                img.paste(self._page_image(old, now), (-shift, 0))
                img.paste(self._page_image(new, now), (WIDTH * (1 if forward else -1) - shift, 0))
            else:
                img = self._page_image(self.current, now)
            img = img.convert("RGBA")
            renderer.dots(img, self.current, len(self.pages))
            if self.toast:
                img.alpha_composite(self._overlay(self.toast[0]) or Image.new("RGBA", img.size))
            if self.touch and _holds(self.touch["zone"]) and not self.touch["moved"] and not self.touch["done"]:
                held = now - self.touch["t0"] - p.PRESS_DELAY
                if held > 0:
                    banner = self._overlay(p.HOLD_OVERLAY + self.touch["zone"]["action"])
                    if banner:
                        img.alpha_composite(banner)
                    _hold_bar(img, min(1.0, held / p.HOLD_FILL))
            return img.convert("RGB")

    def _page_image(self, index: int, now: float) -> Image.Image:
        page = self.pages[index]
        bg = page.get("bg") or {}
        if bg.get("file") in self.files:
            img = self._file_frame(bg["file"], now)
        else:
            img = Image.new("RGB", (WIDTH, HEIGHT), bg.get("color") or "#000000")
        return self._with_overlay(img, page["id"])

    def _with_overlay(self, img: Image.Image, overlay_id: str | None) -> Image.Image:
        ov = self._overlay(overlay_id) if overlay_id else None
        if ov is None:
            return img
        out = img.convert("RGBA")
        out.alpha_composite(ov)
        return out.convert("RGB")

    def _overlay(self, overlay_id: str) -> Image.Image | None:
        if overlay_id not in self.overlays:
            return None
        key = "ov:" + overlay_id
        if key not in self.decoded:
            self.decoded[key] = p.decode_overlay(self.overlays[overlay_id][1])
        return self.decoded[key]

    def _file_frame(self, file_id: str, elapsed: float) -> Image.Image:
        f = self.files.get(file_id)
        if f is None:
            return Image.new("RGB", (WIDTH, HEIGHT))
        key = "file:" + file_id
        if key not in self.decoded:
            self.decoded[key] = _decode_frames(f["data"])
        frames = self.decoded[key]
        if len(frames) == 1:
            return frames[0][0]
        total = sum(d for _, d in frames)
        t = (elapsed * 1000) % total
        for img, d in frames:
            if t < d:
                return img
            t -= d
        return frames[-1][0]

    def status(self) -> dict:
        with self.lock:
            now = self.clock()
            return {"online": self.online(now), "page": self._page_id(), "pages": len(self.pages),
                    "flash_used": self.flash_used(), "flash_total": self.flash_bytes,
                    "files": len(self.files)}


# --- Helpers ---------------------------------------------------------------------------------

def _facing(vx: float, vy: float) -> float:
    """The angle (PIL's, counter-clockwise in degrees) that points the cat's head along its travel:
    upright going right, upside down going left."""
    return -math.degrees(math.atan2(vy, vx))


def _holds(zone: dict | None) -> bool:
    """A long-press zone (the default), as opposed to a tap zone."""
    return zone is not None and zone.get("gesture", "hold") == "hold"


def _decode_frames(data: bytes) -> list[tuple[Image.Image, int]]:
    """Every frame of a JPEG, GIF or MJ1 file, with its duration in ms, sized for the screen.
    Frames with see-through pixels stay RGBA."""
    if data[:3] == p.MJPEG_MAGIC:
        frame_ms, jpegs = p.decode_mjpeg(data)
        return [(_decode_frames(j)[0][0], frame_ms) for j in jpegs]
    with Image.open(io.BytesIO(data)) as im:
        frames = []
        for i in range(getattr(im, "n_frames", 1)):
            im.seek(i)
            frame = im.convert("RGBA")
            if frame.getchannel("A").getextrema()[0] == 255:
                frame = frame.convert("RGB")
            if frame.size != (WIDTH, HEIGHT):
                frame = frame.resize((WIDTH, HEIGHT))
            frames.append((frame, max(20, int(im.info.get("duration", 100)))))
        return frames


def _over(base: Image.Image, frame: Image.Image) -> Image.Image:
    """A file's frame drawn over base: all of it, or only its opaque pixels."""
    if frame.mode != "RGBA":
        return frame
    out = base.convert("RGBA")
    out.alpha_composite(frame)
    return out.convert("RGB")


def _duration(file: dict) -> float:
    """How long the start animation plays at power-on."""
    if file["format"] != "gif":
        return p.STILL_SECONDS
    seconds = sum(d for _, d in _decode_frames(file["data"])) / 1000
    return min(p.ANIM_MAX_SECONDS, max(p.ANIM_MIN_SECONDS, seconds))


def _ease(t: float) -> float:
    return 1 - (1 - t) ** 3


def _dim(img: Image.Image) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(p.DIM_LEVEL)


def _hold_bar(img: Image.Image, progress: float) -> None:
    """The reset banner's bar, filled from the left as the hold goes on (the banner is the PC's)."""
    x, y, w, h = HOLD_BAR
    filled = int(w * progress)
    if filled > 0:
        ImageDraw.Draw(img).rectangle((x, y, x + filled - 1, y + h - 1), fill=GOLD)


_offline_cache: dict[bool, Image.Image] = {}


def offline_screen(was_connected: bool) -> Image.Image:
    """The one screen the firmware draws on its own (baked into it at build time)."""
    if was_connected not in _offline_cache:
        _offline_cache[was_connected] = renderer.offline_screen(
            "PC disconnected" if was_connected else "Waiting for the PC")
    return _offline_cache[was_connected]


class SimRunner:
    """Runs a SimScreen on its own thread, like the firmware's main loop."""

    def __init__(self, screen: SimScreen):
        self.screen = screen
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="sim-screen")

    def start(self) -> "SimRunner":
        self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop.is_set():
            self.screen.poll(0.02)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=1)

