"""What the screen should hold: the visible pages' overlays, their backgrounds as screen-ready
files, where a long press resets something, the event animations (game start, level-up,
death) and the start animation (power-on, and each time the PC connects)."""

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageSequence

from .. import pages as pagelib
from ..media import MediaStore, compose_background
from ..render import renderer
from ..render.data import RenderData
from ..render.theme import BACKGROUND
from . import gif
from . import protocol as p
from .client import Content, FileContent, PageContent

JPEG_QUALITY = 88
# Built-in event animations, made for this project: assets/anims/<kind>.gif, except these.
ANIM_DIR = Path(__file__).resolve().parent.parent / "assets" / "anims"
BUILTIN = {"launch": "start.gif", "boot": "start.gif"}  # the spinning cat
ANIM_FIT = {"fit": "cover", "x": 50, "y": 50}
STILL_SECONDS = p.STILL_SECONDS  # an image (or a video's still frame, for now) shown for an event
MIN_SECONDS = p.ANIM_MIN_SECONDS  # shorter GIFs loop until then
MAX_SECONDS = p.ANIM_MAX_SECONDS
EVENT_LOOPS = {"levelup": 2}  # how many times an event's GIF plays (once if not listed)


class ContentBuilder:
    """Builds Content, converting each background once and remembering the result."""

    def __init__(self, media: MediaStore):
        self.media = media
        self.files: dict[str, FileContent] = {}
        self.seconds: dict[str, float] = {}  # how long each animation file plays

    def build(self, pages: list[dict], data: RenderData) -> Content:
        shown, files = [], {}
        for page in pagelib.visible(pages):
            bg = self.background(page)
            if "file" in bg:
                files[bg["file"]] = self.files[bg["file"]]
            shown.append(PageContent(page["id"], p.encode_overlay(renderer.overlay(page, data)), bg,
                                     pagelib.touch_zones(page)))
        return Content(shown, files)

    def background(self, page: dict) -> dict:
        bg = page["background"]
        if bg["kind"] == "color":
            return {"color": bg.get("value") or BACKGROUND}
        source = self.media.source_path(bg.get("value") or "")
        still = self.media.still_path(bg.get("value") or "")
        if source is None:
            return {"color": BACKGROUND}
        key = f"{bg['value']}|{bg['fit']}|{bg['x']}|{bg['y']}|{source.stat().st_mtime}"
        file_id = "bg-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        if file_id not in self.files:
            if bg["kind"] == "gif":
                self.files[file_id] = FileContent(gif_for_screen(source, bg), "gif")
            elif still is not None:
                # Videos send their first frame for now; MJPEG comes with the firmware media step.
                self.files[file_id] = FileContent(jpeg_for_screen(still, bg), "jpeg")
            else:
                return {"color": BACKGROUND}
        return {"file": file_id, "color": BACKGROUND}


    def animation(self, kind: str, media_id: str = "") -> tuple[str, FileContent, float] | None:
        """The screen file for an event, or for "boot" (the start animation): the friend's
        upload, else the built-in one, else None."""
        source = self.media.source_path(media_id) if media_id else None
        if source is not None:
            meta = self.media.get(media_id)
            still = self.media.still_path(media_id)
            is_gif = meta["kind"] == "gif"
        else:
            source = still = ANIM_DIR / BUILTIN.get(kind, f"{kind}.gif")
            if not source.is_file():
                return None
            is_gif = True
        key = f"{kind}|{source}|{source.stat().st_mtime}"
        file_id = f"anim-{kind}-" + hashlib.sha1(key.encode()).hexdigest()[:8]
        if file_id not in self.files:
            if is_gif:
                data = gif_for_screen(source, ANIM_FIT)
                loops = EVENT_LOOPS.get(kind, 1)
                self.seconds[file_id] = min(MAX_SECONDS, max(MIN_SECONDS, loops * gif_seconds(data)))
                self.files[file_id] = FileContent(data, "gif")
            elif still is not None:
                self.files[file_id] = FileContent(jpeg_for_screen(still, ANIM_FIT), "jpeg")
                self.seconds[file_id] = STILL_SECONDS
            else:
                return None
        # The screen plays "boot" on its own at power-on, so that file has a fixed id.
        return p.BOOT_FILE if kind == "boot" else file_id, self.files[file_id], self.seconds[file_id]


def gif_seconds(data: bytes) -> float:
    with Image.open(io.BytesIO(data)) as im:
        return sum(frame.info.get("duration", 100) for frame in ImageSequence.Iterator(im)) / 1000


def jpeg_for_screen(path: Path, bg: dict) -> bytes:
    with Image.open(path) as im:
        img = compose_background(im, bg["fit"], bg["x"], bg["y"])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def gif_for_screen(path: Path, bg: dict) -> bytes:
    with Image.open(path) as im:
        frames, durations = [], []
        for frame in ImageSequence.Iterator(im):
            frames.append(compose_background(frame, bg["fit"], bg["x"], bg["y"]))
            durations.append(max(20, int(frame.info.get("duration", im.info.get("duration", 100)))))
    return gif.encode(frames, durations)

