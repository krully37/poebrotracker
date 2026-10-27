"""Low-level drawing on the transparent overlay.

Pillow's ImageDraw darkens anti-aliased edges when it draws on a transparent
image (it blends towards transparent black). The overlay is later composited
over arbitrary backgrounds, so every shape is drawn as a coverage mask and
then filled with a solid color, which keeps the edges clean.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .data import RenderData
from .fonts import text_size
from .templates import Box
from .theme import GOLD

SUPERSAMPLE = 4


@dataclass
class Ctx:
    img: Image.Image  # RGBA overlay, transparent where nothing is drawn
    data: RenderData


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    rgb = ImageColor.getrgb(color)[:3]
    return (*rgb, alpha)


def paint(ctx: Ctx, color: str, draw_mask: Callable[[ImageDraw.ImageDraw], None], alpha: int = 255, smooth: bool = False) -> None:
    """Fill `color` through a mask drawn by `draw_mask`.

    With smooth=True the mask is drawn at 4x and scaled down, which anti-aliases
    lines and polygons (Pillow only anti-aliases text). Coordinates passed to the
    callback are then in 4x space.
    """
    scale = SUPERSAMPLE if smooth else 1
    width, height = ctx.img.size
    mask = Image.new("L", (width * scale, height * scale), 0)
    draw_mask(ImageDraw.Draw(mask))
    bbox = mask.getbbox()
    if bbox is None:
        return
    # Only the area actually drawn is scaled, colored and composited: much faster
    # than working on the whole screen for every piece of text.
    x0, y0 = max(0, bbox[0] // scale - 1), max(0, bbox[1] // scale - 1)
    x1, y1 = min(width, -(-bbox[2] // scale) + 1), min(height, -(-bbox[3] // scale) + 1)
    mask = mask.crop((x0 * scale, y0 * scale, x1 * scale, y1 * scale))
    if smooth:
        mask = mask.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    if alpha < 255:
        mask = mask.point(lambda p: p * alpha // 255)
    layer = Image.new("RGBA", mask.size, rgba(color, 0))
    layer.putalpha(mask)
    ctx.img.alpha_composite(layer, (x0, y0))


def text(ctx: Ctx, xy: tuple[float, float], s: str, f: ImageFont.FreeTypeFont, color: str, anchor: str = "ls") -> None:
    paint(ctx, color, lambda d: d.text(xy, s, font=f, fill=255, anchor=anchor))


def cap_height(f: ImageFont.FreeTypeFont) -> int:
    return -f.getbbox("H0", anchor="ls")[1]


def text_in(ctx: Ctx, box: Box, s: str, f: ImageFont.FreeTypeFont, color: str, align: str = "left", valign: str = "middle") -> None:
    """Draw one line of text aligned inside `box`.

    Vertical placement uses the font's capital height, not the text's own bounds,
    so rows of different words share the same baseline.
    """
    left, _, right, _ = f.getbbox(s, anchor="ls")
    w, cap = right - left, cap_height(f)
    descent = f.getmetrics()[1]
    x = {"left": box.x, "center": box.x + (box.w - w) / 2, "right": box.x + box.w - w}[align] - left
    baseline = {
        "top": box.y + cap,
        "middle": box.y + (box.h + cap) / 2,
        "bottom": box.y + box.h - descent * 0.6,
    }[valign]
    text(ctx, (x, baseline), s, f, color)


def truncate(s: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    if text_size(s, f)[0] <= max_w:
        return s
    while s and text_size(s + "…", f)[0] > max_w:
        s = s[:-1]
    return (s.rstrip() + "…") if s else ""


@lru_cache(maxsize=256)
def _load_icon(path: str) -> Image.Image:
    with Image.open(path) as im:
        return im.convert("RGBA")


def icon_image(ctx: Ctx, name: str) -> Image.Image | None:
    lookup = ctx.data.icon if ctx.data else None
    path = lookup(name) if lookup else None
    return _load_icon(str(path)) if path else None


def has_icon(ctx: Ctx, name: str) -> bool:
    return icon_image(ctx, name) is not None or name == "Divine Orb"


def item_icon(ctx: Ctx, name: str, x: float, y: float, size: float) -> bool:
    """Draw the game icon of `name` centered in a size x size square. False if there is none.

    Without the real icon, the Divine Orb falls back to a drawn orb.
    """
    im = icon_image(ctx, name)
    if im is None:
        if name == "Divine Orb":
            divine_icon(ctx, x, y, size)
            return True
        return False
    scale = size / max(im.width, im.height)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    resized = im.resize((w, h), Image.Resampling.LANCZOS)
    ctx.img.alpha_composite(resized, (int(round(x + (size - w) / 2)), int(round(y + (size - h) / 2))))
    return True


def divine_icon(ctx: Ctx, x: float, y: float, size: float) -> None:
    """A simple glowing orb standing for 'divines'. Drawn from scratch, no game asset."""
    s = max(4, int(round(size)))
    big = s * SUPERSAMPLE
    dark = ImageColor.getrgb("#9A6A1E")
    light = ImageColor.getrgb("#FFF4CC")
    gold = ImageColor.getrgb(GOLD)
    # Color layer: filled with the edge color so downscaling never bleeds black into the rim.
    color = Image.new("RGB", (big, big), dark)
    d = ImageDraw.Draw(color)
    steps = 24
    for i in range(steps):
        t = i / (steps - 1)
        r = big / 2 * (1 - t * 0.85)
        # Centre drifts to the upper left, giving a lit-sphere look.
        cx, cy = big / 2 - t * big * 0.12, big / 2 - t * big * 0.12
        mid = [int(a + (b - a) * min(1, t * 1.6)) for a, b in zip(dark, gold)]
        col = mid if t < 0.6 else [int(a + (b - a) * (t - 0.6) / 0.4) for a, b in zip(gold, light)]
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(col))
    # Small four-pointed spark in the middle.
    c, arm, waist = big / 2, big * 0.3, big * 0.06
    d.polygon([(c, c - arm), (c + waist, c - waist), (c + arm, c), (c + waist, c + waist),
               (c, c + arm), (c - waist, c + waist), (c - arm, c), (c - waist, c - waist)], fill=(255, 255, 255))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    color = color.resize((s, s), Image.Resampling.LANCZOS)
    mask = mask.resize((s, s), Image.Resampling.LANCZOS)
    icon = color.convert("RGBA")
    icon.putalpha(mask)
    ctx.img.alpha_composite(icon, (int(round(x)), int(round(y))))
