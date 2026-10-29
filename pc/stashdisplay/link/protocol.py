"""The USB serial protocol between the PC and the screen. Specified in docs/PROTOCOL.md.

Frames: COBS-encoded, ended by a 0x00 byte, so a reader can always resync on the next 0x00.
Inside: type (u8), seq (u16 LE), payload, CRC-32 (u32 LE) of everything before it.
Payloads are small JSON objects, except CHUNK, which is binary.
"""

import json
import struct
import zlib
from dataclasses import dataclass

from PIL import Image, ImageChops

VERSION = 1
BAUD = 921600  # ignored by native USB, used by CH340-style bridges
MAX_CHUNK = 4096  # data bytes per CHUNK frame
MAX_FRAME = MAX_CHUNK + 64  # larger frames are dropped as garbage
ACK_TIMEOUT = 1.0  # seconds before the PC resends a frame
RETRIES = 4
HEARTBEAT = 30  # the PC sends something at least this often
OFFLINE_AFTER = 90  # the screen shows "PC disconnected" after this much silence
HOLD_OVERLAY = "@hold-"

# PC -> screen. Every one is answered by ACK with the same seq.
HELLO = 0x01  # {"version", "time"} -> ACK carries the screen's inventory
PAGES = 0x02  # {"pages": [{"id", "overlay": crc, "bg": {...}, "zones": [...]}]}: order and content
BEGIN = 0x03  # {"xfer", "kind": "overlay"|"file"|"toast", "id", "size", "crc", "format"?, "seconds"?}
CHUNK = 0x04  # binary: xfer u16, offset u32, data
END = 0x05  # {"xfer"}: the screen checks size and CRC, then stores the blob
DELETE = 0x06  # {"id"}: delete a file from flash
PLAY = 0x07  # {"file"?, "overlay"?, "seconds", "over_page"?}: event animation, full screen or over the page
PING = 0x08  # {}: heartbeat
EVENT_ACK = 0x09  # seq = the EVENT being acknowledged
IDLE = 0x0A  # {"sprite": file id | null}: the PC is idle, bounce this sprite on black; null = back to the pages

# Screen -> PC.
ACK = 0x81  # seq = the frame being acknowledged; {"ok": bool, "error"?, ...}
EVENT = 0x82  # {"type": "tap"|"reset"|"page"|"wake", "page", "action"?}; the PC answers EVENT_ACK
LOG = 0x83  # {"text"}: debug output, not acknowledged

NAMES = {v: k for k, v in globals().items() if k.isupper() and isinstance(v, int) and k not in
         ("VERSION", "BAUD", "MAX_CHUNK", "MAX_FRAME", "RETRIES", "HEARTBEAT", "OFFLINE_AFTER")}


class ProtocolError(ValueError):
    pass


@dataclass
class Frame:
    type: int
    seq: int
    payload: bytes = b""

    def json(self) -> dict:
        try:
            value = json.loads(self.payload or b"{}")
        except ValueError as e:
            raise ProtocolError("bad json") from e
        if not isinstance(value, dict):
            raise ProtocolError("json payload must be an object")
        return value

    def __repr__(self) -> str:
        return f"Frame({NAMES.get(self.type, hex(self.type))}, seq={self.seq}, {len(self.payload)} bytes)"


# --- COBS framing --------------------------------------------------------------

def cobs_encode(data: bytes) -> bytes:
    out = bytearray([0])
    code_pos, code = 0, 1
    for b in data:
        if b == 0:
            out[code_pos] = code
            code_pos, code = len(out), 1
            out.append(0)
            continue
        out.append(b)
        code += 1
        if code == 0xFF:
            out[code_pos] = code
            code_pos, code = len(out), 1
            out.append(0)
    out[code_pos] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        if code == 0 or i + code > len(data):
            raise ProtocolError("bad COBS block")
        out += data[i + 1:i + code]
        i += code
        if code < 0xFF and i < len(data):
            out.append(0)
    return bytes(out)


def encode_frame(frame_type: int, seq: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<BH", frame_type, seq & 0xFFFF) + payload
    return cobs_encode(body + struct.pack("<I", zlib.crc32(body))) + b"\x00"


def json_frame(frame_type: int, seq: int, obj: dict | None = None) -> bytes:
    payload = json.dumps(obj or {}, separators=(",", ":")).encode() if obj else b""
    return encode_frame(frame_type, seq, payload)


def chunk_payload(xfer: int, offset: int, data: bytes) -> bytes:
    return struct.pack("<HI", xfer, offset) + data


def parse_chunk(payload: bytes) -> tuple[int, int, bytes]:
    if len(payload) < 6:
        raise ProtocolError("short chunk")
    xfer, offset = struct.unpack_from("<HI", payload)
    return xfer, offset, payload[6:]


class FrameReader:
    """Collects bytes from the wire and returns whole, checked frames. Bad frames are dropped."""

    def __init__(self):
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, data: bytes) -> list[Frame]:
        frames = []
        self.buf += data
        while True:
            end = self.buf.find(0)
            if end < 0:
                if len(self.buf) > MAX_FRAME * 2:  # no delimiter in sight: garbage
                    self.buf.clear()
                    self.dropped += 1
                return frames
            raw, self.buf = bytes(self.buf[:end]), self.buf[end + 1:]
            if not raw:
                continue
            try:
                frames.append(decode_frame(raw))
            except ProtocolError:
                self.dropped += 1


def decode_frame(raw: bytes) -> Frame:
    if len(raw) > MAX_FRAME + MAX_FRAME // 254 + 2:
        raise ProtocolError("frame too long")
    body = cobs_decode(raw)
    if len(body) < 7:
        raise ProtocolError("frame too short")
    (crc,) = struct.unpack_from("<I", body, len(body) - 4)
    if zlib.crc32(body[:-4]) != crc:
        raise ProtocolError("bad CRC")
    frame_type, seq = struct.unpack_from("<BH", body)
    return Frame(frame_type, seq, body[3:-4])


# --- Overlays: RGB565 + 4-bit alpha, zlib -------------------------------------------
#
# Layout before compression: b"OV1", width u16, height u16, then the alpha plane
# (4 bits per pixel, two pixels per byte, high nibble first), then the colour plane
# (RGB565, u16 little-endian per pixel). Fully transparent pixels have colour 0, so
# the mostly-empty overlays compress to a few kB.

OVERLAY_MAGIC = b"OV1"


def _table(fn) -> list[int]:
    return [fn(v) for v in range(256)]


def _interleave(even: bytes, odd: bytes) -> bytes:
    out = bytearray(len(even) + len(odd))
    out[0::2], out[1::2] = even, odd
    return bytes(out)


def encode_overlay(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    w, h = img.size
    if w % 2:
        raise ValueError("overlay width must be even")
    r, g, b, a = img.split()
    a4 = a.point(_table(lambda v: (v * 15 + 127) // 255))
    visible = a4.point(_table(lambda v: 255 if v else 0))
    black = Image.new("L", img.size, 0)
    r, g, b = (Image.composite(c, black, visible) for c in (r, g, b))
    # Two alpha nibbles per byte: even pixels in the high nibble.
    alpha = a4.tobytes()
    hi = Image.frombytes("L", (w // 2, h), alpha[0::2]).point(_table(lambda v: v << 4))
    lo = Image.frombytes("L", (w // 2, h), alpha[1::2])
    alpha_plane = ImageChops.add(hi, lo).tobytes()
    # RGB565 split into its low and high bytes; the bit ranges never overlap, so add() is an OR.
    low = ImageChops.add(g.point(_table(lambda v: ((v >> 2) & 7) << 5)), b.point(_table(lambda v: v >> 3)))
    high = ImageChops.add(r.point(_table(lambda v: (v >> 3) << 3)), g.point(_table(lambda v: v >> 5)))
    colour_plane = _interleave(low.tobytes(), high.tobytes())
    raw = OVERLAY_MAGIC + struct.pack("<HH", w, h) + alpha_plane + colour_plane
    return zlib.compress(raw, 9)


def decode_overlay(blob: bytes) -> Image.Image:
    """Back to RGBA, as the screen will see it (for the simulator and tests)."""
    try:
        raw = zlib.decompress(blob)
    except zlib.error as e:
        raise ProtocolError("bad overlay data") from e
    if raw[:3] != OVERLAY_MAGIC or len(raw) < 7:
        raise ProtocolError("not an overlay")
    w, h = struct.unpack_from("<HH", raw, 3)
    n = w * h
    if len(raw) != 7 + n // 2 + n * 2:
        raise ProtocolError("overlay size mismatch")
    alpha_plane = raw[7:7 + n // 2]
    colour = raw[7 + n // 2:]
    hi = alpha_plane.translate(bytes(_table(lambda v: (v >> 4) * 17)))
    lo = alpha_plane.translate(bytes(_table(lambda v: (v & 15) * 17)))
    a = Image.frombytes("L", (w, h), _interleave(hi, lo))
    low = Image.frombytes("L", (w, h), colour[0::2])
    high = Image.frombytes("L", (w, h), colour[1::2])
    r = high.point(_table(lambda v: (v & 0xF8) | (v >> 5)))
    g = ImageChops.add(high.point(_table(lambda v: ((v & 7) << 5) | ((v & 7) >> 1))),
                       low.point(_table(lambda v: (v >> 5) << 2)))
    b = low.point(_table(lambda v: ((v & 31) << 3) | ((v & 31) >> 2)))
    return Image.merge("RGBA", (r, g, b, a))


# --- Video backgrounds: MJ1 -------------------------------------------------------------------
#
# "MJ1" | frame_ms u16 | count u16 | (count + 1) offsets u32, from the start of the file | JPEGs.
# The screen reads one frame at a time from flash, so it needs to find each one.

MJPEG_MAGIC = b"MJ1"
VIDEO_FPS = 12
VIDEO_MAX_SECONDS = 10
VIDEO_JPEG_QUALITY = 70


def encode_mjpeg(frames: list[bytes], frame_ms: int) -> bytes:
    head = len(MJPEG_MAGIC) + 4 + 4 * (len(frames) + 1)
    offsets, at = [], head
    for frame in frames:
        offsets.append(at)
        at += len(frame)
    offsets.append(at)
    return MJPEG_MAGIC + struct.pack(f"<HH{len(offsets)}I", frame_ms, len(frames), *offsets) + b"".join(frames)


def decode_mjpeg(blob: bytes) -> tuple[int, list[bytes]]:
    """(frame_ms, the JPEG frames), as the screen reads them."""
    if blob[:3] != MJPEG_MAGIC or len(blob) < 7:
        raise ProtocolError("not a video")
    frame_ms, count = struct.unpack_from("<HH", blob, 3)
    offsets = struct.unpack_from(f"<{count + 1}I", blob, 7)
    if offsets[-1] != len(blob) or any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ProtocolError("bad video offsets")
    return frame_ms, [blob[a:b] for a, b in zip(offsets, offsets[1:])]


def crc_hex(data: bytes) -> str:
    return f"{zlib.crc32(data):08x}"


# --- Screen behaviour (the firmware uses the same numbers) ----------------------------

TOUCH_SLOP = 12  # px a finger may move and still count as still
SWIPE_MIN = 60  # px of horizontal travel for a page change
PRESS_DELAY = 0.4  # s of holding still before the reset banner appears
HOLD_FILL = 1.5  # s for its bar to fill; lifting earlier cancels
# While holding, the screen shows the overlay HOLD_OVERLAY + action ("@hold-reset_rate"), rendered by
# the PC, and fills theme.HOLD_BAR in theme.GOLD from the left as the hold goes on.
SLIDE_SECONDS = 0.28
DIM_LEVEL = 0.3  # backlight while the PC is away
EVENT_DIM = 0.4  # brightness of the page under an over-the-page event animation
FLASH_BYTES = 11 * 1024 * 1024  # file storage on the screen (§5 of the scope)
# The start animation, played at power-on without the PC: a GIF plays once, looping until
# ANIM_MIN_SECONDS if shorter and cut at ANIM_MAX_SECONDS; an image shows for STILL_SECONDS.
# Event animations follow the same rule, worked out by the PC and sent in PLAY.
BOOT_FILE = "boot"
ANIM_MIN_SECONDS = 3.0
ANIM_MAX_SECONDS = 10.0
STILL_SECONDS = 4.0
# The idle cat: a sprite file (overlay format) that bounces off the screen's edges on black,
# turning to face where it goes. The edges are those of its visible pixels, as turned.
IDLE_FILE = "idle"
IDLE_SPEED = 100.0  # px/s
IDLE_TURN = 0.25  # s: time constant of the turn towards the new direction after a bounce
