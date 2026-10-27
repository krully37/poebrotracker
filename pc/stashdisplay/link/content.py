"""What the screen should hold: the visible pages' overlays, their backgrounds as screen-ready
files, and where a long press resets something."""

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageSequence

from .. import pages as pagelib
from ..media import MediaStore, compose_background
from ..render import renderer
from ..render.data import RenderData
from ..render.theme import BACKGROUND
from . import protocol as p
from .client import Content, FileContent, PageContent

JPEG_QUALITY = 88


class ContentBuilder:
    """Builds Content, converting each background once and remembering the result."""

    def __init__(self, media: MediaStore):
        self.media = media
        self.files: dict[str, FileContent] = {}

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
            frames.append(compose_background(frame, bg["fit"], bg["x"], bg["y"]).quantize(256))
            durations.append(max(20, int(frame.info.get("duration", im.info.get("duration", 100)))))
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)
    return buf.getvalue()

