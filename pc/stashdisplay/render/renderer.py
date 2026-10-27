"""Turns a page into images.

- `overlay`: what gets sent to the screen, a transparent RGBA layer with the text and charts.
- `background`: the page's background as the screen will show it (first frame for GIF/video).
- `preview`: background + overlay + pagination dots, exactly what the screen will display.
"""

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from . import draw, frames
from .data import RenderData, fmt_duration
from .draw import Ctx
from .fonts import NAME_FAMILY, TITLE_FAMILY, font, text_size
from .templates import HEADER_BOX, TEMPLATES, Box
from .theme import BACKGROUND, DOTS_Y, FAINT, HEIGHT, LABEL, MUTED, STALE, TITLE, WHITE, WIDTH
from .widgets import NUMBER_FAMILY, WIDGETS, faint_frame, slot_title, without_title

# Above this many pages the screen shows "3/9" instead of dots.
MAX_DOTS = 8


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
        data = ctx.data
        if data.synced_at is None:
            label, color = "waiting for data", LABEL
        elif data.stale:
            label, color = f"stale · {fmt_duration(data.now - data.synced_at)} ago", STALE
        else:
            ago = fmt_duration(data.now - data.synced_at)
            label, color = ("synced just now" if ago == "now" else f"synced {ago} ago"), LABEL
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
            box = frames.tooltip(ctx, box, slot_title(slot))
            options = without_title(slot)
        elif slot["frame"] == "plain":
            box = frames.tooltip(ctx, box)
        WIDGETS[slot["widget"]].render(ctx, box, options)
    return ctx.img


def background(page: dict, media_dir: Path | None = None) -> Image.Image:
    bg = page["background"]
    if bg["kind"] == "color":
        return Image.new("RGB", (WIDTH, HEIGHT), bg.get("value") or BACKGROUND)
    path = Path(bg.get("value") or "")
    if media_dir is not None and not path.is_absolute():
        path = media_dir / path
    if bg["kind"] in ("image", "gif") and path.is_file():
        with Image.open(path) as im:
            im.seek(0)
            # Cover the screen and crop the overflow, like a CSS background-size: cover.
            return ImageOps.fit(im.convert("RGB"), (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    # Video frames are not decoded yet; show a placeholder so the layout can still be judged.
    img = Image.new("RGB", (WIDTH, HEIGHT), "#101216")
    ctx = Ctx(img.convert("RGBA"), None)  # type: ignore[arg-type]
    draw.text_in(ctx, Box(0, 0, WIDTH, HEIGHT), f"{bg['kind']} background", font("Inter", 14, 500), FAINT, "center")
    return ctx.img.convert("RGB")


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


def preview(page: dict, data: RenderData, index: int, count: int, media_dir: Path | None = None) -> Image.Image:
    img = background(page, media_dir).convert("RGBA")
    img.alpha_composite(overlay(page, data))
    dots(img, index, count)
    return img.convert("RGB")


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
