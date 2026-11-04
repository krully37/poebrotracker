"""Turns a page into images.

- `overlay`: what gets sent to the screen, a transparent RGBA layer with the text and charts.
- `background`: the page's background as the screen will show it (first frame for GIF/video).
- `preview`: background + overlay + pagination dots, exactly what the screen will display.
"""

from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ..media import compose_background

from . import draw, frames
from .data import RenderData, fmt_duration
from .draw import Ctx
from .fonts import NAME_FAMILY, TITLE_FAMILY, font, text_size
from .fonts import fit as fit_font
from .templates import HEADER_BOX, TEMPLATES, Box
from .theme import BACKGROUND, DOTS_Y, FAINT, FRAME_FILL, FRAME_LINE_DIM, HEIGHT, HOLD_BAR, LABEL, MUTED, STALE, TITLE, WHITE, WIDTH
from .widgets import NUMBER_FAMILY, WIDGETS, faint_frame, slot_header, without_title

# Above this many pages the screen shows "3/9" instead of dots.
MAX_DOTS = 8


def sync_label(data: RenderData) -> tuple[str, str]:
    """The top bar's freshness text and its colour. A failed read says why ("Cookie expired",
    "WealthyExile unavailable"...) straight away (docs/SCOPE.md §6)."""
    if data.error:
        return data.error, STALE
    if data.synced_at is None:
        return "waiting for data", LABEL
    ago = fmt_duration(data.now - data.synced_at)
    if data.stale:
        return f"stale · {ago} ago", STALE
    return ("synced just now" if ago == "now" else f"synced {ago} ago"), LABEL


def header(ctx: Ctx, page: dict) -> None:
    opts = page["header"]
    if not any(opts.values()):
        return
    box = HEADER_BOX
    frames.page_header(ctx, box)
    right = box.x + box.w
    if opts["clock"]:
        cf = font(NUMBER_FAMILY, 17, 600)
        clock = datetime.fromtimestamp(ctx.data.now).astimezone().strftime("%H:%M")
        cw = text_size(clock, cf)[0]
        draw.text_in(ctx, Box(right - cw, box.y + 3, cw, box.h - 8), clock, cf, TITLE, "right")
        right -= cw + 12
    if opts["synced"]:
        sf = font(NAME_FAMILY, 13, 400)
        label, color = sync_label(ctx.data)
        sw = text_size(label, sf)[0]
        draw.text_in(ctx, Box(right - sw, box.y + 3, sw, box.h - 8), label, sf, color, "right")
        right -= sw + 12
    if opts["title"]:
        tf = font(TITLE_FAMILY, 21, 400)
        title = draw.truncate(page["name"], tf, right - box.x)
        draw.text_in(ctx, Box(box.x, box.y + 3, right - box.x, box.h - 8), title, tf, TITLE, "left")


def overlay(page: dict, data: RenderData, show_empty_slots: bool = False) -> Image.Image:
    ctx = Ctx(Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0)), data)
    header(ctx, page)
    for name, box in TEMPLATES[page["template"]].slots.items():
        slot = page["slots"].get(name)
        if slot is None:
            if show_empty_slots:
                faint_frame(ctx, box)
            continue
        options = slot
        if slot["frame"] == "tooltip":
            title, tint = slot_header(slot, data)
            box = frames.tooltip(ctx, box, title, tint)
            options = without_title(slot)
        elif slot["frame"] == "plain":
            box = frames.tooltip(ctx, box)
        WIDGETS[slot["widget"]].render(ctx, box, options)
    return ctx.img


def background(page: dict, still_for: Callable[[str], Path | None] | None = None) -> Image.Image:
    """The page background as the screen shows it; GIF and video show their first frame."""
    bg = page["background"]
    if bg["kind"] == "color":
        return Image.new("RGB", (WIDTH, HEIGHT), bg.get("value") or BACKGROUND)
    path = still_for(bg.get("value") or "") if still_for else None
    if path is not None:
        return _composed(str(path), path.stat().st_mtime, bg["fit"], bg["x"], bg["y"]).copy()
    # No still yet (missing file, or a video whose first frame is not extracted yet).
    img = Image.new("RGB", (WIDTH, HEIGHT), "#101216")
    ctx = Ctx(img.convert("RGBA"), None)  # type: ignore[arg-type]
    draw.text_in(ctx, Box(0, 0, WIDTH, HEIGHT), f"{bg['kind']} background", font("Inter", 14, 500), FAINT, "center")
    return ctx.img.convert("RGB")


@lru_cache(maxsize=32)
def _composed(path: str, mtime: float, fit: str, x: int, y: int) -> Image.Image:
    with Image.open(path) as im:
        return compose_background(im, fit, x, y)


def dots(img: Image.Image, index: int, count: int) -> None:
    """Pagination as the screen draws it. Only used for previews; the screen draws its own."""
    if count <= 1:
        return
    ctx = Ctx(img, None)  # type: ignore[arg-type]
    if count > MAX_DOTS:
        f = font("Inter", 11, 600)
        draw.text_in(ctx, Box(0, DOTS_Y - 7, WIDTH, 14), f"{index + 1}/{count}", f, MUTED, "center")
        return
    gap, r = 14, 3
    x0 = WIDTH / 2 - gap * (count - 1) / 2
    k = draw.SUPERSAMPLE
    for i in range(count):
        cx = x0 + i * gap
        color = WHITE if i == index else "#55595F"
        draw.paint(ctx, color, lambda d, cx=cx: d.ellipse(((cx - r) * k, (DOTS_Y - r) * k, (cx + r) * k, (DOTS_Y + r) * k), fill=255), smooth=True)


def preview(page: dict, data: RenderData, index: int, count: int,
            still_for: Callable[[str], Path | None] | None = None) -> Image.Image:
    img = background(page, still_for).convert("RGBA")
    img.alpha_composite(overlay(page, data))
    dots(img, index, count)
    return img.convert("RGB")


def toast(text: str) -> Image.Image:
    """A short message over the page ("Session reset", "Div/h reset"), as a full-screen overlay."""
    ctx = Ctx(Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0)), None)  # type: ignore[arg-type]
    f = font(TITLE_FAMILY, 20, 400)
    w = text_size(text, f)[0] + 48
    box = Box(int((WIDTH - w) / 2), HEIGHT - 96, int(w), 44)
    draw.paint(ctx, "#0A0806", lambda d: d.rectangle((box.x, box.y, box.x + box.w, box.y + box.h), fill=255), alpha=235)
    frames.tooltip(ctx, box)
    draw.text_in(ctx, box, text, f, TITLE, "center")
    return ctx.img


def hold_banner(text: str) -> Image.Image:
    """Shown while a finger holds on a reset zone ("Resetting div/h"): the text over an empty bar,
    at the top of the screen. The screen fills the bar (theme.HOLD_BAR) as the hold goes on."""
    ctx = Ctx(Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0)), None)  # type: ignore[arg-type]
    bx, by, bw, bh = HOLD_BAR
    box = Box(bx - 32, 6, bw + 64, by + bh + 12 - 6)
    draw.paint(ctx, FRAME_FILL, lambda d: d.rectangle((box.x, box.y, box.x + box.w, box.y + box.h), fill=255), alpha=235)
    frames.tooltip(ctx, box)
    f = fit_font(text, TITLE_FAMILY, 400, box.w - 24, 20)
    draw.text_in(ctx, Box(box.x, box.y + 4, box.w, by - box.y - 6), text, f, TITLE, "center")
    draw.paint(ctx, "#1A1510", lambda d: d.rectangle((bx, by, bx + bw - 1, by + bh - 1), fill=255))
    draw.paint(ctx, FRAME_LINE_DIM, lambda d: d.rectangle((bx - 1, by - 1, bx + bw, by + bh), outline=255, width=1))
    return ctx.img


def event_card(title: str, subtitle: str, color: str = TITLE) -> Image.Image:
    """Stand-in for an event animation that has no GIF: large text on a dark screen."""
    ctx = Ctx(Image.new("RGBA", (WIDTH, HEIGHT), "#050403"), None)  # type: ignore[arg-type]
    box = Box(40, 92, WIDTH - 80, 136)
    frames.tooltip(ctx, box)
    tf = fit_font(title, TITLE_FAMILY, 400, box.w - 40, 64)
    draw.text_in(ctx, Box(box.x, box.y + 14, box.w, 76), title, tf, color, "center")
    sf = font(NAME_FAMILY, 20, 400)
    draw.text_in(ctx, Box(box.x, box.y + 92, box.w, 28), draw.truncate(subtitle, sf, box.w - 40), sf, LABEL, "center")
    return ctx.img


def offline_screen(message: str) -> Image.Image:
    """The screen the firmware shows on its own when the PC is away (baked into the firmware)."""
    ctx = Ctx(Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND), None)  # type: ignore[arg-type]
    box = Box(90, 110, WIDTH - 180, 100)
    frames.tooltip(ctx, box)
    draw.text_in(ctx, Box(box.x, box.y + 18, box.w, 40), message, font(TITLE_FAMILY, 24, 400), TITLE, "center")
    draw.text_in(ctx, Box(box.x, box.y + 58, box.w, 24), "Stash Display", font(NAME_FAMILY, 14, 400), MUTED, "center")
    return ctx.img.convert("RGB")


def contact_sheet(images: list[Image.Image], labels: list[str], columns: int = 2, scale: int = 1) -> Image.Image:
    """All page previews on one image, with a label under each, for quick review."""
    pad, label_h = 16, 22
    w, h = WIDTH * scale, HEIGHT * scale
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGBA", (pad + columns * (w + pad), pad + rows * (h + label_h + pad)), "#1B1D21")
    ctx = Ctx(sheet, None)  # type: ignore[arg-type]
    lf = font("Inter", 13, 600)
    for i, (im, label) in enumerate(zip(images, labels)):
        x = pad + (i % columns) * (w + pad)
        y = pad + (i // columns) * (h + label_h + pad)
        sheet.paste(im.resize((w, h), Image.Resampling.NEAREST), (x, y))
        draw.text_in(ctx, Box(x, y + h + 4, w, label_h - 4), label, lf, MUTED, "left", "top")
    return sheet.convert("RGB")
