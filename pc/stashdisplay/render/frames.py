"""PoE item-tooltip style frames, drawn in code from the game's colors and shapes."""

from PIL import Image

from . import draw
from .draw import Ctx
from .fonts import TITLE_FAMILY, fit
from .templates import Box
from .theme import FRAME_FILL, FRAME_LINE, FRAME_LINE_DIM, HEADER_EDGE, HEADER_MID, TITLE

FILL_ALPHA = 215


def gradient_bar(ctx: Ctx, box: Box, edge: str = HEADER_EDGE, mid: str = HEADER_MID) -> None:
    """A bar that is lighter in the middle and darker at both ends, like a tooltip header."""
    w, h = max(1, box.w), max(1, box.h)
    ramp = Image.new("L", (w, 1))
    ramp.putdata([int(255 * (1 - abs(2 * i / max(1, w - 1) - 1)) ** 0.8) for i in range(w)])
    mask = ramp.resize((w, h))
    bar = Image.composite(Image.new("RGBA", (w, h), draw.rgba(mid)), Image.new("RGBA", (w, h), draw.rgba(edge)), mask)
    ctx.img.alpha_composite(bar, (box.x, box.y))


def diamond(ctx: Ctx, cx: float, cy: float, r: float, color: str = FRAME_LINE) -> None:
    k = draw.SUPERSAMPLE
    draw.paint(ctx, color, lambda d: d.polygon(
        [(cx * k, (cy - r) * k), ((cx + r) * k, cy * k), (cx * k, (cy + r) * k), ((cx - r) * k, cy * k)], fill=255), smooth=True)


def hline(ctx: Ctx, x0: float, x1: float, y: float, color: str = FRAME_LINE, alpha: int = 255) -> None:
    draw.paint(ctx, color, lambda d: d.line([(x0, y), (x1, y)], fill=255, width=1), alpha=alpha)


def tooltip(ctx: Ctx, box: Box, title: str = "") -> Box:
    """Draw a tooltip frame (with a header bar when there is a title). Returns the content area."""
    x0, y0, x1, y1 = box.x, box.y, box.x + box.w - 1, box.y + box.h - 1
    draw.paint(ctx, FRAME_FILL, lambda d: d.rectangle((x0, y0, x1, y1), fill=255), alpha=FILL_ALPHA)
    draw.paint(ctx, FRAME_LINE_DIM, lambda d: d.rectangle((x0, y0, x1, y1), outline=255, width=1))
    if not title:
        return Box(box.x + 8, box.y + 6, box.w - 16, box.h - 12)
    hh = 22 if box.h >= 90 else 18
    gradient_bar(ctx, Box(box.x + 1, box.y + 1, box.w - 2, hh))
    hline(ctx, x0, x1, y0, FRAME_LINE, alpha=160)
    hline(ctx, x0, x1, y0 + hh, FRAME_LINE)
    cy = y0 + hh / 2
    diamond(ctx, x0 + 6, cy, 3)
    diamond(ctx, x1 - 6, cy, 3)
    tf = fit(title, TITLE_FAMILY, 400, box.w - 34, int(hh * 0.62), max_size=16)
    draw.text_in(ctx, Box(box.x + 14, box.y, box.w - 28, hh), draw.truncate(title, tf, box.w - 34), tf, TITLE, "center", "middle")
    return Box(box.x + 8, box.y + hh + 6, box.w - 16, box.h - hh - 11)


def page_header(ctx: Ctx, box: Box) -> None:
    """The bar behind the page title, clock and sync status."""
    gradient_bar(ctx, Box(0, 0, ctx.img.width, box.h), edge="#0B0907", mid="#2C241A")
    hline(ctx, 0, ctx.img.width, box.h - 1, FRAME_LINE)
    diamond(ctx, ctx.img.width / 2, box.h - 1, 3.5)
