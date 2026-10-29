"""Background media uploaded in the settings page.

Each upload gets a random id and its own folder:
    media/<id>/source.<ext>   the file as uploaded
    media/<id>/still.png      first frame, full size (cropped at render time)
    media/<id>/frames.bin     a video's frames, JPEGs each after its length (u32 LE)
    media/<id>/meta.json      kind, original name, size, frame count...

A video's still and frames come from the browser (it can decode the video; Python cannot
without ffmpeg). link/content.py converts media for the screen.
"""

import io
import json
import secrets
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .link.protocol import VIDEO_FPS, VIDEO_MAX_SECONDS
from .render.theme import HEIGHT, WIDTH

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
JPEG_START = bytes([0xFF, 0xD8])


class MediaError(ValueError):
    pass


class MediaStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, media_id: str) -> Path:
        if not media_id or not media_id.isalnum():
            raise MediaError("bad media id")
        return self.root / media_id

    def add(self, filename: str, data: bytes) -> dict:
        ext = Path(filename).suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            if len(data) > MAX_VIDEO_BYTES:
                raise MediaError("video too large")
            return self._store(filename, data, ext, {"kind": "video", "frames": None, "needs_still": True})
        if len(data) > MAX_IMAGE_BYTES:
            raise MediaError("image too large")
        try:
            with Image.open(io.BytesIO(data)) as im:
                frames = getattr(im, "n_frames", 1)
                kind = "gif" if frames > 1 else "image"
                im.seek(0)
                still = im.convert("RGB")
                ext = ".gif" if kind == "gif" else ".png"
                if kind == "image":
                    # Re-encode stills as PNG: drops metadata and odd formats.
                    buf = io.BytesIO()
                    still.save(buf, "PNG")
                    data = buf.getvalue()
        except (UnidentifiedImageError, OSError) as e:
            raise MediaError("not an image or video") from e
        meta = self._store(filename, data, ext, {"kind": kind, "frames": frames, "needs_still": False})
        still.save(self._dir(meta["id"]) / "still.png")
        meta.update(width=still.width, height=still.height)
        self._write_meta(meta)
        return meta

    def _store(self, filename: str, data: bytes, ext: str, extra: dict) -> dict:
        media_id = secrets.token_hex(6)
        folder = self._dir(media_id)
        folder.mkdir()
        (folder / f"source{ext}").write_bytes(data)
        meta = {"id": media_id, "name": Path(filename).name[:120], "bytes": len(data), "ext": ext, **extra}
        self._write_meta(meta)
        return meta

    def _write_meta(self, meta: dict) -> None:
        (self._dir(meta["id"]) / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def set_still(self, media_id: str, png: bytes) -> dict:
        """Store the first frame of a video, decoded by the browser."""
        meta = self.get(media_id)
        try:
            with Image.open(io.BytesIO(png)) as im:
                still = im.convert("RGB")
        except (UnidentifiedImageError, OSError) as e:
            raise MediaError("not an image") from e
        still.save(self._dir(media_id) / "still.png")
        meta.update(needs_still=False, width=still.width, height=still.height)
        self._write_meta(meta)
        return meta

    def set_frames(self, media_id: str, data: bytes) -> dict:
        """Store a video's frames, decoded by the browser: each a JPEG after its length (u32 LE),
        at protocol.VIDEO_FPS, at most protocol.VIDEO_MAX_SECONDS of them."""
        meta = self.get(media_id)
        frames, at = [], 0
        while at + 4 <= len(data) and len(frames) < VIDEO_FPS * VIDEO_MAX_SECONDS:
            (n,) = struct.unpack_from("<I", data, at)
            frame = data[at + 4:at + 4 + n]
            if len(frame) != n or not frame.startswith(JPEG_START):
                raise MediaError("not a JPEG frame")
            frames.append(frame)
            at += 4 + n
        if not frames:
            raise MediaError("no frames")
        (self._dir(media_id) / "frames.bin").write_bytes(b"".join(struct.pack("<I", len(f)) + f for f in frames))
        meta.update(video_frames=len(frames))
        self._write_meta(meta)
        return meta

    def video_frames(self, media_id: str) -> list[bytes]:
        """A video's frames (JPEGs at full size), or [] when the browser has not sent them."""
        path = self._dir(media_id) / "frames.bin"
        if not path.exists():
            return []
        data, frames, at = path.read_bytes(), [], 0
        while at + 4 <= len(data):
            (n,) = struct.unpack_from("<I", data, at)
            frames.append(data[at + 4:at + 4 + n])
            at += 4 + n
        return frames

    def frames_path(self, media_id: str) -> Path | None:
        path = self._dir(media_id) / "frames.bin"
        return path if path.exists() else None

    def get(self, media_id: str) -> dict:
        path = self._dir(media_id) / "meta.json"
        if not path.exists():
            raise MediaError("unknown media")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        out = []
        for meta_file in sorted(self.root.glob("*/meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            out.append(json.loads(meta_file.read_text(encoding="utf-8")))
        return out

    def delete(self, media_id: str) -> None:
        folder = self._dir(media_id)
        if folder.exists():
            shutil.rmtree(folder)

    def source_path(self, media_id: str) -> Path | None:
        """The uploaded file itself (PNG for images, GIF, or the original video)."""
        try:
            meta = self.get(media_id)
        except MediaError:
            return None
        path = self._dir(media_id) / f"source{meta['ext']}"
        return path if path.exists() else None

    def still_path(self, media_id: str) -> Path | None:
        try:
            path = self._dir(media_id) / "still.png"
        except MediaError:
            return None
        return path if path.exists() else None

    def thumbnail(self, media_id: str, size: tuple[int, int] = (160, 107)) -> bytes | None:
        path = self.still_path(media_id)
        if path is None:
            return None
        with Image.open(path) as im:
            thumb = ImageOps.fit(im.convert("RGB"), size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb.save(buf, "PNG")
        return buf.getvalue()


def compose_background(still: Image.Image, fit: str, x: int, y: int, fill: str = "#000000") -> Image.Image:
    """Fit a still to the screen. cover: fill and crop around (x%, y%); contain: whole image, padded."""
    still = still.convert("RGB")
    if fit == "contain":
        return ImageOps.pad(still, (WIDTH, HEIGHT), Image.Resampling.LANCZOS, color=fill, centering=(x / 100, y / 100))
    return ImageOps.fit(still, (WIDTH, HEIGHT), Image.Resampling.LANCZOS, centering=(x / 100, y / 100))
