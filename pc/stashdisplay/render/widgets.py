"""Widget types that can go into a template slot.

Each widget declares its options (used to fill in defaults now, and to build
the settings form later) and a function that draws it inside a box.

Every slot also has a `frame` option, handled by the renderer: "tooltip" draws
a PoE tooltip frame with the widget's title in its header, "plain" draws the
frame without a header, "none" draws nothing.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import draw
from .data import METRICS, RenderData, fmt_amount, fmt_duration, fmt_metric
from .draw import Ctx
from .fonts import BUNDLED, FALLBACK, NAME_FAMILY, TITLE_FAMILY, fit, font, text_size
from .templates import Box
from .theme import FAINT, GOLD, LABEL, MUTED, SPARK, WHITE, signed_color

FRAMES = ["tooltip", "plain", "none"]
FONT_CHOICES = [*BUNDLED, *FALLBACK]
# Fontin has no "×" sign, so quantities are written "x148".
NUMBER_FAMILY = "Fontin"


@dataclass
class Option:
    key: str
    kind: str  # metric, text, bool, int, choice, font, weight, color, items
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


def slot_label(ctx: Ctx, box: Box, label: str, align: str = "left") -> Box:
    """Small-caps label at the top of a slot; returns the space left under it."""
    if not label:
        return box
    size = label_size(box) + 2
    lf = font(TITLE_FAMILY, size, 400)
    draw.text_in(ctx, Box(box.x, box.y, box.w, size), draw.truncate(label, lf, box.w), lf, LABEL, align, "top")
    used = size + 8
    return Box(box.x, box.y + used, box.w, box.h - used)


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
        if metric.kind != "chaos":
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
