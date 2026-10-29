"""Widget types that can go into a template slot.

Each widget declares its options (used to fill in defaults now, and to build
the settings form later) and a function that draws it inside a box.

Every slot also has a `frame` option, handled by the renderer: "tooltip" draws
a PoE tooltip frame with the widget's title in its header, "plain" draws the
frame without a header, "none" draws nothing.
"""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from PIL import Image

from . import draw
from .data import DIV_KINDS, METRICS, RenderData, fmt_amount, fmt_clock, fmt_duration, fmt_metric
from .draw import Ctx
from .fonts import BUNDLED, FALLBACK, NAME_FAMILY, TITLE_FAMILY, fit, font, text_size
from .templates import Box
from .theme import FAINT, FRAME_LINE, GOLD, LABEL, MUTED, SPARK, STALE, WHITE, signed_color

FRAMES = ["tooltip", "plain", "none"]
FONT_CHOICES = [*BUNDLED, *FALLBACK]
# Fontin has no "×" sign, so quantities are written "x148".
NUMBER_FAMILY = "Fontin"


@dataclass
class Option:
    key: str
    kind: str  # metric, text, multiline, bool, int, choice, font, weight, color, items
    default: Any
    label: str
    choices: list[str] = field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None


@dataclass
class WidgetType:
    id: str
    name: str
    description: str
    options: list[Option]
    render: Callable[[Ctx, Box, dict], None]
    frame: str = "tooltip"  # default frame for new slots with this widget

    def defaults(self) -> dict:
        return {o.key: o.default for o in self.options}


WIDGETS: dict[str, WidgetType] = {}


def widget(id: str, name: str, description: str, options: list[Option], frame: str = "tooltip"):
    def register(fn):
        WIDGETS[id] = WidgetType(id, name, description, options, fn, frame)
        return fn
    return register


def _font_options(family: str = NUMBER_FAMILY, weight: int = 700, color: str = "auto") -> list[Option]:
    return [
        Option("font", "font", family, "Font", choices=FONT_CHOICES),
        Option("weight", "weight", weight, "Weight", minimum=100, maximum=900),
        Option("color", "color", color, "Color ('auto' = green/red for gains)"),
    ]


# --- Titles: shown in the tooltip header, or above the content without one ---

def slot_title(slot: dict) -> str:
    kind = slot["widget"]
    if kind == "value":
        if slot["label"] == "-":
            return ""
        return slot["label"] or METRICS.get(slot["metric"], METRICS["total"]).label
    if kind == "stack_value":
        return "" if slot["label"] == "-" else (slot["label"] or slot["name"])
    return slot.get("title", "")


def without_title(slot: dict) -> dict:
    """The slot's options with its title removed, once the frame header shows it."""
    key = {"value": "label", "stack_value": "label"}.get(slot["widget"], "title")
    if key not in slot:
        return slot
    return {**slot, key: "-" if key == "label" else ""}


# --- Placeholders for free text: "{rate} div/h", "since {session_since}" ----

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(data: RenderData) -> dict[str, str]:
    values = {k: fmt_metric(m.kind, data.metrics.get(k)) for k, m in METRICS.items()}
    now = datetime.fromtimestamp(data.now).astimezone()
    start = datetime.fromtimestamp(data.session_start).astimezone() if data.session_start else None
    values.update(
        league=data.league or "--",
        time=now.strftime("%H:%M"),
        date=now.strftime("%a %d %b"),
        session_since=start.strftime("%H:%M") if start else "--",
        session_duration=fmt_duration(data.now - data.session_start) if start else "--",
        synced=fmt_duration(data.now - data.synced_at) if data.synced_at else "never",
    )
    cur = data.current_map
    values.update(
        map=cur.name if cur else "--",
        map_tier=cur.tier if cur else "--",
        map_time=fmt_clock(cur.seconds) if cur else "--",
    )
    return values


def fill_placeholders(template: str, data: RenderData) -> str:
    values = placeholders(data)
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def color_for(option: str, data: RenderData, metric: str | None) -> str:
    """Resolve 'auto': green/red for gains, white for everything else."""
    if option != "auto":
        return option
    if metric in METRICS and METRICS[metric].kind in ("signed", "rate"):
        return signed_color(data.metrics.get(metric))
    return WHITE


def first_metric(template: str) -> str | None:
    for m in PLACEHOLDER.finditer(template):
        if m.group(1) in METRICS:
            return m.group(1)
    return None


# --- Shared layouts ----------------------------------------------------------

def label_size(box: Box) -> int:
    return int(min(16, max(11, box.h * 0.13)))


def under_label(box: Box, label: str) -> Box:
    """The space slot_label leaves under its label."""
    if not label:
        return box
    used = label_size(box) + 2 + 8
    return Box(box.x, box.y + used, box.w, box.h - used)


def slot_label(ctx: Ctx, box: Box, label: str, align: str = "left") -> Box:
    """Small-caps label at the top of a slot; returns the space left under it."""
    if not label:
        return box
    size = label_size(box) + 2
    lf = font(TITLE_FAMILY, size, 400)
    draw.text_in(ctx, Box(box.x, box.y, box.w, size), draw.truncate(label, lf, box.w), lf, LABEL, align, "top")
    return under_label(box, label)


def icon_room(cap: int) -> tuple[int, int]:
    """Icon size and gap for a number whose digits are `cap` pixels tall."""
    return int(cap * 1.3), int(cap * 0.15)


def fit_with_icon(text: str, family: str, weight: int, max_w: int, max_h: int, icon: bool, max_size: int = 150):
    """Like fonts.fit, but the width also has to hold the icon, which grows with the font."""
    lo, hi = 6, max(6, max_size)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = font(family, mid, weight)
        w, h = text_size(text, f)
        cap = draw.cap_height(f)
        extra = sum(icon_room(cap)) if icon else 0
        if w + extra <= max_w and max(h, cap) <= max_h:
            lo = mid
        else:
            hi = mid - 1
    return font(family, lo, weight)


def value_block(ctx: Ctx, box: Box, *, label: str, main: str, sub: str, color: str, sub_color: str,
                icon: str | None, family: str, weight: int, align: str, size: int = 0) -> None:
    """Small label on top, a big number (with an optional item icon), an optional line below.

    `size` caps the number's font size so several tiles can match; 0 fills the slot.
    It still shrinks when the number would not fit.
    """
    box = slot_label(ctx, box, label, align)
    sub_h = int(min(17, max(11, box.h * 0.18))) if sub else 0
    main_h = box.h - (sub_h + 6 if sub else 0)
    max_text_h = int(main_h * 0.72)
    if main == "--":
        # No value yet: a quiet dash instead of a giant placeholder.
        main, icon, color, max_text_h = "—", None, MUTED, int(main_h * 0.3)
    mf = fit_with_icon(main, family, weight, box.w, max_text_h, bool(icon), size or 150)
    w, _ = text_size(main, mf)
    cap = draw.cap_height(mf)
    icon_size, gap = icon_room(cap) if icon else (0, 0)
    group_w = icon_size + gap + w
    gx = {"left": box.x, "center": box.x + (box.w - group_w) / 2, "right": box.x + box.w - group_w}[align]
    baseline = box.y + (main_h + cap) / 2
    if icon:
        draw.item_icon(ctx, icon, gx, baseline - cap / 2 - icon_size / 2, icon_size)
    draw.text(ctx, (gx + icon_size + gap - mf.getbbox(main, anchor="ls")[0], baseline), main, mf, color)
    if sub:
        sf = fit(sub, NUMBER_FAMILY, 500, box.w, sub_h, max_size=17)
        draw.text_in(ctx, Box(box.x, box.y + box.h - sub_h, box.w, sub_h), sub, sf, sub_color, align, "bottom")


def list_title(ctx: Ctx, box: Box, title: str) -> Box:
    return slot_label(ctx, box, title)


def rows(box: Box, count: int) -> list[Box]:
    row_h = box.h / max(1, count)
    return [Box(box.x, int(box.y + i * row_h), box.w, int(row_h)) for i in range(count)]


def row_fonts(row: Box, scale: float = 0.55, largest: int = 18):
    size = int(min(largest, max(10, row.h * scale)))
    return font(NAME_FAMILY, size + 1, 400), font(NUMBER_FAMILY, size, 700), font(NUMBER_FAMILY, size, 500)


def row_icon(ctx: Ctx, name: str, row: Box, x: float) -> float:
    """Item icon at the start of a list row; returns where the text starts.

    The space is kept even without an icon, so names stay aligned.
    """
    size = row.h * 0.9
    draw.item_icon(ctx, name, x, row.y + (row.h - size) / 2, size)
    return x + size + 6


def amount_with_unit(ctx: Ctx, row: Box, right: float, value: float, f, unit: str = "Divine Orb", icon: bool = True) -> float:
    """Right-aligned amount, optionally followed by a currency icon; returns the left edge used."""
    size = int(f.size * 1.15)
    if icon and draw.has_icon(ctx, unit):
        draw.item_icon(ctx, unit, right - size, row.y + (row.h - size) / 2, size)
        right -= size + 3
        text = fmt_amount(value) if unit == "Divine Orb" else f"{value:,.0f}"
    else:
        text = fmt_amount(value) if unit == "Divine Orb" else f"{value:,.0f}c"
    w = text_size(text, f)[0]
    draw.text_in(ctx, Box(right - w, row.y, w, row.h), text, f, WHITE, "right")
    return right - w


def empty(ctx: Ctx, box: Box, message: str) -> None:
    f = font(NAME_FAMILY, 14, 400)
    draw.text_in(ctx, box, draw.truncate(message, f, box.w), f, MUTED, "center", "middle")


# --- Widgets -------------------------------------------------------------------

@widget("value", "Number", "One metric shown big, with an optional label and a line below.", [
    Option("metric", "metric", "total", "Metric", choices=list(METRICS)),
    Option("label", "text", "", "Label (empty = metric name, '-' = none)"),
    Option("sub", "text", "", "Line below, e.g. '{rate} div/h'"),
    Option("icon", "bool", True, "Currency icon"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=150),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(),
])
def render_value(ctx: Ctx, box: Box, o: dict) -> None:
    metric = METRICS.get(o["metric"], METRICS["total"])
    label = "" if o["label"] == "-" else (o["label"] or metric.label)
    value = ctx.data.metrics.get(metric.id)
    main = fmt_metric(metric.kind, value)
    icon = None
    if o["icon"]:
        if metric.kind in DIV_KINDS:
            icon = "Divine Orb"
        elif draw.has_icon(ctx, "Chaos Orb") and value is not None:
            icon, main = "Chaos Orb", f"{value:,.0f}"  # the icon replaces the "c"
    sub = fill_placeholders(o["sub"], ctx.data) if o["sub"] else ""
    value_block(
        ctx, box, label=label, main=main, sub=sub,
        color=color_for(o["color"], ctx.data, metric.id),
        sub_color=color_for("auto", ctx.data, first_metric(o["sub"])) if first_metric(o["sub"]) else MUTED,
        icon=icon, family=o["font"], weight=o["weight"], align=o["align"], size=o["size"],
    )


@widget("sparkline", "Chart", "The stash value over time as a line.", [
    Option("title", "text", "", "Title"),
    Option("series", "choice", "total", "Data", choices=["total", "session"]),
    Option("color", "color", SPARK, "Line color"),
    Option("fill", "bool", True, "Shade under the line"),
    Option("range", "bool", True, "Show min and max"),
], frame="plain")
def render_sparkline(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    values = ctx.data.session_series if o["series"] == "session" else ctx.data.total_series
    if len(values) < 2:
        empty(ctx, box, "Collecting data…")
        return
    label_w = 0
    if o["range"]:
        lf = font(NUMBER_FAMILY, 11, 500)
        hi, lo = fmt_amount(max(values)), fmt_amount(min(values))
        label_w = max(text_size(hi, lf)[0], text_size(lo, lf)[0]) + 6
        draw.text_in(ctx, Box(box.x + box.w - label_w + 6, box.y, label_w, 12), hi, lf, MUTED, "left", "top")
        draw.text_in(ctx, Box(box.x + box.w - label_w + 6, box.y + box.h - 12, label_w, 12), lo, lf, MUTED, "left", "bottom")
    k = draw.SUPERSAMPLE
    x0, y0, w, h = (box.x + 3) * k, (box.y + 4) * k, (box.w - label_w - 6) * k, (box.h - 8) * k
    lo_v, hi_v = min(values), max(values)
    span = hi_v - lo_v or 1.0
    pts = [(x0 + i * w / (len(values) - 1), y0 + h - (v - lo_v) / span * h) for i, v in enumerate(values)]
    if o["fill"]:
        draw.paint(ctx, o["color"], lambda d: d.polygon([(pts[0][0], y0 + h), *pts, (pts[-1][0], y0 + h)], fill=255), alpha=45, smooth=True)
    draw.paint(ctx, o["color"], lambda d: d.line(pts, fill=255, width=2 * k, joint="curve"), smooth=True)
    lx, ly = pts[-1]
    draw.paint(ctx, o["color"], lambda d: d.ellipse((lx - 3.5 * k, ly - 3.5 * k, lx + 3.5 * k, ly + 3.5 * k), fill=255), smooth=True)


@widget("top_items", "Most valuable items", "Your highest-value items. Several of the same item count as one row.", [
    Option("title", "text", "Most valuable", "Title"),
    Option("count", "int", 8, "Rows", minimum=1, maximum=12),
    Option("quantity", "bool", True, "Show quantity"),
    Option("icons", "bool", True, "Item icons"),
    Option("unit_icons", "bool", False, "Divine icon after each value"),
])
def render_top_items(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    items = sorted(ctx.data.snapshot.items, key=lambda i: i.value, reverse=True) if ctx.data.snapshot else []
    if not items:
        empty(ctx, box, "No data yet")
        return
    for row, item in zip(rows(box, o["count"]), items):
        nf, vf, qf = row_fonts(row)
        left = row_icon(ctx, item.name, row, row.x) if o["icons"] else row.x
        name_right = amount_with_unit(ctx, row, row.x + row.w, item.value, vf, icon=o["unit_icons"]) - 8
        if o["quantity"]:
            qty = f"x{item.quantity:,}"
            qw = text_size(qty, qf)[0]
            draw.text_in(ctx, Box(name_right - qw, row.y, qw, row.h), qty, qf, MUTED, "right")
            name_right -= qw + 6
        name = draw.truncate(item.name, nf, name_right - left)
        draw.text_in(ctx, Box(left, row.y, name_right - left, row.h), name, nf, WHITE, "left")


@widget("tab_totals", "Stash tabs", "Value of each stash tab, with bars.", [
    Option("title", "text", "Tabs", "Title"),
    Option("count", "int", 8, "Rows", minimum=1, maximum=12),
    Option("bars", "bool", True, "Show bars"),
    Option("unit_icons", "bool", False, "Divine icon after each value"),
])
def render_tab_totals(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    tabs = sorted(ctx.data.tabs(), key=lambda t: t.value, reverse=True)
    if not tabs:
        empty(ctx, box, "No data yet")
        return
    top = tabs[0].value or 1.0
    for row, tab in zip(rows(box, o["count"]), tabs):
        nf, vf, _ = row_fonts(row)
        if o["bars"]:
            bw = max(4, row.w * tab.value / top)
            pad = row.h * 0.12
            draw.paint(ctx, GOLD, lambda d, r=row: d.rectangle(
                (r.x, r.y + pad, r.x + bw, r.y + r.h - pad), fill=255), alpha=34)
        name_right = amount_with_unit(ctx, row, row.x + row.w - 4, tab.value, vf, icon=o["unit_icons"]) - 8
        name = draw.truncate(tab.name, nf, name_right - row.x - 6)
        draw.text_in(ctx, Box(row.x + 6, row.y, name_right - row.x - 6, row.h), name, nf, WHITE, "left")


@widget("item_price", "Item prices", "Prices of chosen items from poe.ninja.", [
    Option("title", "text", "Prices", "Title"),
    Option("items", "items", ["Mirror of Kalandra"], "Items"),
    Option("unit", "choice", "div", "Unit", choices=["div", "chaos"]),
    Option("change", "bool", True, "Show 7-day change"),
    Option("icons", "bool", True, "Item icons"),
])
def render_item_price(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    names = o["items"] or []
    if not names:
        empty(ctx, box, "No items chosen")
        return
    for row, name in zip(rows(box, max(len(names), 3)), names):
        nf, vf, qf = row_fonts(row, scale=0.5, largest=19)
        left = row_icon(ctx, name, row, row.x) if o["icons"] else row.x
        price = ctx.data.item_prices.get(name)
        right = row.x + row.w
        if price is not None and o["change"] and price.change is not None:
            ct = f"{price.change:+.0f}%"
            cw = text_size(ct, qf)[0]
            draw.text_in(ctx, Box(right - cw, row.y, cw, row.h), ct, qf, signed_color(price.change), "right")
            right -= cw + 8
        if price is None:
            dash = "—"
            dw = text_size(dash, vf)[0]
            draw.text_in(ctx, Box(right - dw, row.y, dw, row.h), dash, vf, MUTED, "right")
            right -= dw
        elif o["unit"] == "div" and price.div is not None:
            right = amount_with_unit(ctx, row, right, price.div, vf)
        else:
            right = amount_with_unit(ctx, row, right, price.chaos, vf, unit="Chaos Orb")
        label = draw.truncate(name, nf, right - 8 - left)
        draw.text_in(ctx, Box(left, row.y, right - 8 - left, row.h), label, nf, WHITE, "left")


@widget("stack_value", "Stack or tab", "The value of one item stack or one stash tab.", [
    Option("match", "choice", "item", "Look up", choices=["item", "tab"]),
    Option("name", "text", "Divine Orb", "Item or tab name"),
    Option("label", "text", "", "Label (empty = the name, '-' = none)"),
    Option("icon", "bool", True, "Divine icon"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=150),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(color=WHITE),
])
def render_stack_value(ctx: Ctx, box: Box, o: dict) -> None:
    wanted = o["name"].strip().lower()
    value, sub = None, ""
    if o["match"] == "tab":
        value = next((t.value for t in ctx.data.tabs() if t.name.lower() == wanted), None)
    elif ctx.data.snapshot:
        item = next((i for i in ctx.data.snapshot.items if i.name.lower() == wanted), None)
        if item:
            value, sub = item.value, f"x{item.quantity:,}"
    value_block(
        ctx, box, label="" if o["label"] == "-" else (o["label"] or o["name"]),
        main=fmt_amount(value) if value is not None else "--",
        sub=sub, color=color_for(o["color"], ctx.data, None), sub_color=MUTED,
        icon="Divine Orb" if o["icon"] else None, family=o["font"], weight=o["weight"], align=o["align"],
        size=o["size"],
    )


@widget("text", "Text", "Free text. Placeholders like {total}, {rate}, {league}, {time} are filled in.", [
    Option("text", "text", "{league}", "Text"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=120),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(family=NAME_FAMILY, weight=400, color=LABEL),
], frame="none")
def render_text(ctx: Ctx, box: Box, o: dict) -> None:
    s = fill_placeholders(o["text"], ctx.data)
    if not s:
        return
    if o["size"]:
        f = font(o["font"], o["size"], o["weight"])
        s = draw.truncate(s, f, box.w)
    else:
        f = fit(s, o["font"], o["weight"], box.w, int(box.h * 0.75), max_size=120)
    color = color_for(o["color"], ctx.data, first_metric(o["text"]))
    draw.text_in(ctx, box, s, f, color, o["align"], "middle")


NOTE_MIN, NOTE_MAX = 10, 72  # font sizes tried when the size is 0 (fit the card)


def note_lines(paragraphs: list[str], f, width: int) -> list[tuple[bool, str, int]]:
    """Word-wrap the note: (starts a bullet, text, indent) for each line on screen."""
    out = []
    for p in paragraphs:
        bullet = p.startswith("- ")
        indent = int(f.size * 0.9) if bullet else 0
        words = (p[2:] if bullet else p).split()
        if not words:
            out.append((False, "", 0))  # blank line kept as spacing
            continue
        line, first = "", bullet
        for word in words:
            trial = f"{line} {word}" if line else word
            if line and text_size(trial, f)[0] > width - indent:
                out.append((first, line, indent))
                line, first = word, False
            else:
                line = trial
        out.append((first, line, indent))
    return out


def note_line_height(f) -> int:
    ascent, descent = f.getmetrics()
    return int((ascent + descent) * 1.08)


@widget("notes", "Notes", "Your own text over several lines. Line breaks are kept, a line starting with \"- \" "
        "becomes a bullet, and placeholders like {total} are filled in.", [
    Option("title", "text", "Notes", "Title"),
    Option("text", "multiline", "- Sell the divines\n- Buy a Mageblood\nSession so far: {session}", "Text"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=NOTE_MAX),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(family=NAME_FAMILY, weight=400, color=WHITE),
])
def render_notes(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    paragraphs = fill_placeholders(str(o["text"]), ctx.data).replace("\r", "").split("\n")
    while paragraphs and not paragraphs[-1].strip():
        paragraphs.pop()
    if not paragraphs:
        empty(ctx, box, "Empty note")
        return

    def layout(size: int):
        f = font(o["font"], size, o["weight"])
        return f, note_lines(paragraphs, f, box.w), note_line_height(f)

    if o["size"]:
        f, lines, line_h = layout(o["size"])
    else:
        # The largest size at which every line fits; the smallest one otherwise.
        lo, hi = NOTE_MIN, NOTE_MAX
        while lo < hi:
            mid = (lo + hi + 1) // 2
            _, mid_lines, mid_h = layout(mid)
            lo, hi = (mid, hi) if len(mid_lines) * mid_h <= box.h else (lo, mid - 1)
        f, lines, line_h = layout(lo)
    if line_h > box.h:
        # Not even one line fits (a thin footer slot): shrink until one does.
        size = f.size
        while size > 6 and line_h > box.h:
            size -= 1
            f, lines, line_h = layout(size)
        if line_h > box.h:
            return
    room = box.h // line_h
    cut = len(lines) > room
    lines = lines[:room]
    color = color_for(o["color"], ctx.data, None)
    k = draw.SUPERSAMPLE
    for i, (bullet, text, indent) in enumerate(lines):
        if cut and i == len(lines) - 1:
            text += "…"
        text = draw.truncate(text, f, box.w - indent)
        w = indent + text_size(text, f)[0]
        x = {"left": box.x, "center": box.x + (box.w - w) / 2, "right": box.x + box.w - w}[o["align"]]
        row = Box(int(x + indent), box.y + i * line_h, int(w - indent) + 2, line_h)
        draw.text_in(ctx, row, text, f, color, "left", "middle")
        if bullet:
            r, cx, cy = f.size * 0.13, x + indent * 0.35, row.y + row.h / 2
            draw.paint(ctx, GOLD, lambda d, cx=cx, cy=cy, r=r: d.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=255), smooth=True)


# --- Media card: what the PC plays, with buttons the screen sends back as taps ------------------

MEDIA_BUTTONS = ("media_prev", "media_toggle", "media_next")
MIN_BUTTON_W = 50  # px; the 3.5" panel has about 6.5 px per mm


def media_layout(box: Box, cover: bool = True, buttons: bool = True) -> tuple[Box | None, Box, list[tuple[str, Box]]]:
    """Cover (or None), text area, and the buttons as (action, box), inside the card's content box.

    pages.touch_zones uses the same boxes for the screen's tap zones.
    """
    bh = int(min(64, max(24, box.h * 0.36)))
    side = min(box.h, int(box.w * 0.38)) if cover and box.w >= 180 and box.h >= 56 else 0
    # Buttons sit under the text, beside the cover, when each gets a finger's width (about
    # 8 mm); otherwise they take a row across the whole card, under the cover and the text.
    beside = not buttons or (box.w - (side + 10 if side else 0)) / 3 >= MIN_BUTTON_W
    top_h = box.h if beside else box.h - bh - 4
    if not beside:
        side = min(top_h, int(box.w * 0.38)) if cover and top_h >= 40 else 0
    cover_box = Box(box.x, box.y + (top_h - side) // 2, side, side) if side else None
    x = box.x + (side + 10 if side else 0)
    w = box.x + box.w - x
    if not buttons:
        return cover_box, Box(x, box.y, w, box.h), []
    row_x, row_w, row_y = (x, w, box.y + box.h - bh) if beside else (box.x, box.w, box.y + box.h - bh)
    third = row_w / 3
    row = [(a, Box(int(row_x + i * third), row_y, int(third), bh)) for i, a in enumerate(MEDIA_BUTTONS)]
    text = Box(x, box.y, w, max(0, row_y - box.y - 4) if beside else top_h)
    return cover_box, text, row


@lru_cache(maxsize=8)
def _cover_image(data: bytes, side: int) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGBA")
    except OSError:
        return None
    s = min(im.size)
    left, top = (im.width - s) // 2, (im.height - s) // 2
    return im.crop((left, top, left + s, top + s)).resize((side, side), Image.Resampling.LANCZOS)


def _media_text(ctx: Ctx, box: Box, now) -> None:
    if box.h < 12 or box.w < 30:
        return
    if now is None:
        f = font(NAME_FAMILY, int(min(18, max(11, box.h * 0.3))), 400)
        draw.text_in(ctx, box, draw.truncate("Nothing playing", f, box.w), f, MUTED, "left", "middle")
        return
    sub = now.artist or now.app
    sub_h = int(min(18, max(10, box.h * 0.22))) if sub else 0
    title_h = box.h - (sub_h + 4 if sub else 0)
    most = 2 if title_h >= 56 else 1
    # Shrink the title (down to about two thirds) to fit its lines, then cut what is left.
    largest = int(min(26, max(10, title_h / most * 0.62)))
    for size in range(largest, max(10, largest * 2 // 3) - 1, -1):
        f = font(NAME_FAMILY, size, 400)
        lines = [t for _, t, _ in note_lines([now.title], f, box.w)]
        if len(lines) <= most:
            break
    if len(lines) > most:
        lines = lines[:most - 1] + [" ".join(lines[most - 1:])]  # the last line takes the rest, cut below
    line_h = note_line_height(f)
    y = box.y + max(0, (box.h - len(lines) * line_h - (sub_h + 4 if sub else 0)) // 2)
    for line in lines:
        draw.text_in(ctx, Box(box.x, y, box.w, line_h), draw.truncate(line, f, box.w), f, WHITE, "left", "middle")
        y += line_h
    if sub:
        sf = font(NAME_FAMILY, sub_h, 400)
        draw.text_in(ctx, Box(box.x, y + 2, box.w, sub_h + 2), draw.truncate(sub, sf, box.w), sf, MUTED, "left", "middle")


def _media_button(ctx: Ctx, b: Box, action: str, now) -> None:
    """Previous, play/pause and next, drawn as shapes (Fontin has no such glyphs)."""
    s = min(b.h * 0.42, b.w * 0.34)
    cx, cy = b.x + b.w / 2, b.y + b.h / 2
    enabled = now is not None and {"media_prev": now.can_prev, "media_next": now.can_next}.get(action, True)
    color = WHITE if enabled else FAINT
    k = draw.SUPERSAMPLE
    polys, rects = [], []
    if action == "media_toggle":
        r = s * 0.95
        draw.paint(ctx, GOLD if enabled else FAINT, lambda d: d.ellipse(
            ((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), outline=255, width=2 * k), smooth=True)
        if now is not None and now.playing:
            bw, bh = s * 0.2, s * 0.9
            rects += [(cx - bw * 1.4, cy - bh / 2, cx - bw * 0.4, cy + bh / 2), (cx + bw * 0.4, cy - bh / 2, cx + bw * 1.4, cy + bh / 2)]
        else:
            polys.append([(cx - s * 0.3, cy - s * 0.45), (cx + s * 0.45, cy), (cx - s * 0.3, cy + s * 0.45)])
    else:
        d = 1 if action == "media_next" else -1
        polys.append([(cx - d * s * 0.4, cy - s * 0.4), (cx + d * s * 0.25, cy), (cx - d * s * 0.4, cy + s * 0.4)])
        x0, x1 = sorted((cx + d * s * 0.27, cx + d * s * 0.42))
        rects.append((x0, cy - s * 0.4, x1, cy + s * 0.4))

    def shapes(dr):
        for poly in polys:
            dr.polygon([(x * k, y * k) for x, y in poly], fill=255)
        for x0, y0, x1, y1 in rects:
            dr.rectangle((x0 * k, y0 * k, x1 * k, y1 * k), fill=255)

    draw.paint(ctx, color, shapes, smooth=True)


@widget("media", "Now playing", "What the PC is playing (Spotify, a browser, most players), "
        "with previous, play/pause and next buttons to tap on the screen.", [
    Option("title", "text", "Now playing", "Title"),
    Option("cover", "bool", True, "Cover art"),
    Option("buttons", "bool", True, "Buttons"),
])
def render_media(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    now = ctx.data.media
    cover, text, buttons = media_layout(box, o["cover"], o["buttons"])
    if cover:
        img = _cover_image(now.cover, cover.w) if now is not None and now.cover else None
        if img is not None:
            ctx.img.alpha_composite(img, (cover.x, cover.y))
        else:
            draw.paint(ctx, FAINT, lambda d: d.rectangle((cover.x, cover.y, cover.x + cover.w - 1, cover.y + cover.h - 1), outline=255, width=1))
    _media_text(ctx, text, now)
    for action, b in buttons:
        _media_button(ctx, b, action, now)


# --- Current map: the map tracker's card (docs/SCOPE.md §5c) -------------------------------------

MAP_STATES = {"paused": ("Paused", STALE), "out": ("Outside the map", MUTED)}


def map_tags(ctx: Ctx, box: Box, tags: list[str], f) -> None:
    """Mechanic tags as small framed labels on one row, as many as fit, then "+2" for the rest."""
    pad = max(3, f.size // 3)
    x, right = box.x, box.x + box.w
    for i, tag in enumerate(tags):
        w = text_size(tag, f)[0] + 2 * pad
        rest = len(tags) - i - 1
        more_w = text_size(f"+{rest}", f)[0] + pad if rest else 0
        if x + w + more_w > right:
            more = f"+{len(tags) - i}"
            draw.text_in(ctx, Box(int(x), box.y, max(1, int(right - x)), box.h), more, f, MUTED, "left")
            return
        draw.paint(ctx, FRAME_LINE, lambda d, x=x, w=w: d.rounded_rectangle(
            (x, box.y, x + w - 1, box.y + box.h - 1), radius=3, outline=255, width=1))
        draw.text_in(ctx, Box(int(x + pad), box.y, int(w - 2 * pad) + 1, box.h), tag, f, LABEL, "left")
        x += w + pad


@widget("current_map", "Current map", "The map being run, or the last one: its name, tier, a live timer, deaths, "
        "portals and the league mechanics met. Read from the game's log, Client.txt.", [
    Option("title", "text", "Current map", "Title"),
    Option("mechanics", "bool", True, "Mechanics"),
])
def render_current_map(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    cur = ctx.data.current_map
    if cur is None:
        empty(ctx, box, "No map yet")
        return
    timer = fmt_clock(cur.seconds)
    if box.h < 64:
        # A thin slot (a footer): everything on one line.
        line = f"{cur.name}  ·  {cur.tier}  ·  {timer}"
        f = fit(line, NAME_FAMILY, 400, box.w, int(box.h * 0.75), max_size=22)
        draw.text_in(ctx, box, draw.truncate(line, f, box.w), f, WHITE, "left", "middle")
        return
    gap = 4
    line_h = int(min(24, max(12, box.h * 0.2)))
    small_h = int(min(16, max(10, box.h * 0.13)))
    # Name and tier.
    tf = font(NUMBER_FAMILY, line_h, 700)
    tier_w = text_size(cur.tier, tf)[0]
    draw.text_in(ctx, Box(box.x + box.w - tier_w, box.y, tier_w, line_h), cur.tier, tf, GOLD, "right")
    nf = font(NAME_FAMILY, line_h + 1, 400)
    name_w = box.w - tier_w - 8
    draw.text_in(ctx, Box(box.x, box.y, name_w, line_h), draw.truncate(cur.name, nf, name_w), nf, WHITE, "left")
    # Deaths and portals at the bottom, the tags above them when there is room.
    sf = font(NAME_FAMILY, small_h, 400)
    info_y = box.y + box.h - small_h
    info = f"Deaths {cur.deaths}  ·  Portals {cur.portals}"
    draw.text_in(ctx, Box(box.x, info_y, box.w, small_h), draw.truncate(info, sf, box.w), sf, MUTED, "left")
    timer_top, timer_bottom = box.y + line_h + gap, info_y - gap
    tags = cur.mechanics if o["mechanics"] else []
    tag_h = small_h + 4
    if tags and timer_bottom - tag_h - gap - timer_top >= line_h:
        map_tags(ctx, Box(box.x, timer_bottom - tag_h, box.w, tag_h), tags, font(NAME_FAMILY, small_h - 1, 400))
        timer_bottom -= tag_h + gap
    # The live timer, with "Paused" or "Outside the map" beside it.
    timer_box = Box(box.x, timer_top, box.w, max(1, timer_bottom - timer_top))
    state, state_color = MAP_STATES.get(cur.state, ("", WHITE))
    if state:
        state_w = text_size(state, sf)[0]
        if state_w <= box.w * 0.45:
            draw.text_in(ctx, Box(box.x + box.w - state_w, timer_box.y, state_w, timer_box.h), state, sf, state_color, "right")
            timer_box = Box(box.x, timer_box.y, box.w - state_w - 8, timer_box.h)
    # Fitted on 8s, so the size does not jump as the digits change.
    big = fit(re.sub(r"\d", "8", timer), NUMBER_FAMILY, 700, timer_box.w, timer_box.h, max_size=90)
    draw.text_in(ctx, timer_box, timer, big, WHITE if cur.state == "running" else MUTED, "left", "middle")


@widget("clock", "Clock", "The time, optionally with the date.", [
    Option("hours", "choice", "24h", "Format", choices=["24h", "12h"]),
    Option("date", "bool", True, "Show the date"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=150),
    Option("align", "choice", "center", "Alignment", choices=["left", "center", "right"]),
    *_font_options(color=WHITE),
], frame="none")
def render_clock(ctx: Ctx, box: Box, o: dict) -> None:
    now = datetime.fromtimestamp(ctx.data.now).astimezone()
    main = now.strftime("%H:%M") if o["hours"] == "24h" else now.strftime("%I:%M %p").lstrip("0")
    value_block(
        ctx, box, label="", main=main, sub=now.strftime("%A %d %B") if o["date"] else "",
        color=color_for(o["color"], ctx.data, None), sub_color=MUTED, icon=None,
        family=o["font"], weight=o["weight"], align=o["align"], size=o["size"],
    )


def faint_frame(ctx: Ctx, box: Box) -> None:
    """Outline of an empty slot (used by the builder preview)."""
    draw.paint(ctx, FAINT, lambda d: d.rounded_rectangle((box.x, box.y, box.x + box.w, box.y + box.h), radius=6, outline=255, width=1))
