"""Widget types that can go into a template slot.

Each widget declares its options (used to fill in defaults now, and to build
the settings form later) and a function that draws it inside a box.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import draw
from .data import METRICS, RenderData, fmt_amount, fmt_duration, fmt_metric
from .draw import Ctx
from .fonts import FAMILIES, fit, font, text_size
from .templates import Box
from .theme import FAINT, GOLD, MUTED, SPARK, WHITE, signed_color


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

    def defaults(self) -> dict:
        return {o.key: o.default for o in self.options}


WIDGETS: dict[str, WidgetType] = {}


def widget(id: str, name: str, description: str, options: list[Option]):
    def register(fn):
        WIDGETS[id] = WidgetType(id, name, description, options, fn)
        return fn
    return register


def _font_options(family: str = "Inter", weight: int = 700, color: str = "auto") -> list[Option]:
    return [
        Option("font", "font", family, "Font", choices=list(FAMILIES)),
        Option("weight", "weight", weight, "Weight", minimum=100, maximum=900),
        Option("color", "color", color, "Color ('auto' = green/red for gains)"),
    ]


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
    size = label_size(box)
    lf = font("Cinzel", size, 700)
    draw.text_in(ctx, Box(box.x, box.y, box.w, size), draw.truncate(label.upper(), lf, box.w), lf, MUTED, align, "top")
    used = size + 8
    return Box(box.x, box.y + used, box.w, box.h - used)


def value_block(ctx: Ctx, box: Box, *, label: str, main: str, sub: str, color: str, sub_color: str,
                icon: bool, family: str, weight: int, align: str) -> None:
    """Small label on top, a big number (with optional divine icon), an optional line below."""
    box = slot_label(ctx, box, label, align)
    sub_h = int(min(17, max(11, box.h * 0.16))) if sub else 0
    main_h = box.h - (sub_h + 8 if sub else 0)
    max_text_h = int(main_h * 0.75)
    if main == "--":
        # No value yet: a quiet dash instead of a giant placeholder.
        main, icon, color, max_text_h = "—", False, MUTED, int(main_h * 0.3)
    # The icon is as tall as the digits; reserve room for it before fitting the number.
    gap = int(max_text_h * 0.18) if icon else 0
    reserve = max_text_h + gap if icon else 0
    mf = fit(main, family, weight, box.w - reserve, max_text_h, max_size=150)
    w, _ = text_size(main, mf)
    cap = draw.cap_height(mf)
    icon_size = int(cap * 1.1) if icon else 0
    gap = int(cap * 0.2) if icon else 0
    group_w = icon_size + gap + w
    gx = {"left": box.x, "center": box.x + (box.w - group_w) / 2, "right": box.x + box.w - group_w}[align]
    baseline = box.y + (main_h + cap) / 2
    if icon:
        draw.divine_icon(ctx, gx, baseline - cap / 2 - icon_size / 2, icon_size)
    draw.text(ctx, (gx + icon_size + gap - mf.getbbox(main, anchor="ls")[0], baseline), main, mf, color)
    if sub:
        sf = fit(sub, "Inter", 500, box.w, sub_h, max_size=17)
        draw.text_in(ctx, Box(box.x, box.y + box.h - sub_h, box.w, sub_h), sub, sf, sub_color, align, "bottom")


def list_title(ctx: Ctx, box: Box, title: str) -> Box:
    return slot_label(ctx, box, title)


def rows(box: Box, count: int) -> list[Box]:
    row_h = box.h / max(1, count)
    return [Box(box.x, int(box.y + i * row_h), box.w, int(row_h)) for i in range(count)]


def empty(ctx: Ctx, box: Box, message: str) -> None:
    f = font("Inter", 13, 500)
    draw.text_in(ctx, box, draw.truncate(message, f, box.w), f, MUTED, "center", "middle")


# --- Widgets -------------------------------------------------------------------

@widget("value", "Number", "One metric shown big, with an optional label and a line below.", [
    Option("metric", "metric", "total", "Metric", choices=list(METRICS)),
    Option("label", "text", "", "Label (empty = metric name, '-' = none)"),
    Option("sub", "text", "", "Line below, e.g. '{rate} div/h'"),
    Option("icon", "bool", True, "Divine icon"),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(),
])
def render_value(ctx: Ctx, box: Box, o: dict) -> None:
    metric = METRICS.get(o["metric"], METRICS["total"])
    label = "" if o["label"] == "-" else (o["label"] or metric.label)
    main = fmt_metric(metric.kind, ctx.data.metrics.get(metric.id))
    sub = fill_placeholders(o["sub"], ctx.data) if o["sub"] else ""
    value_block(
        ctx, box, label=label, main=main, sub=sub,
        color=color_for(o["color"], ctx.data, metric.id),
        sub_color=color_for("auto", ctx.data, first_metric(o["sub"])) if first_metric(o["sub"]) else MUTED,
        icon=o["icon"] and metric.kind != "chaos", family=o["font"], weight=o["weight"], align=o["align"],
    )


@widget("sparkline", "Chart", "The stash value over time as a line.", [
    Option("series", "choice", "total", "Data", choices=["total", "session"]),
    Option("color", "color", SPARK, "Line color"),
    Option("fill", "bool", True, "Shade under the line"),
    Option("range", "bool", True, "Show min and max"),
])
def render_sparkline(ctx: Ctx, box: Box, o: dict) -> None:
    values = ctx.data.session_series if o["series"] == "session" else ctx.data.total_series
    if len(values) < 2:
        empty(ctx, box, "Collecting data…")
        return
    label_w = 0
    if o["range"]:
        lf = font("Inter", 11, 500)
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


@widget("top_items", "Top stacks", "The most valuable item stacks.", [
    Option("title", "text", "Top stacks", "Title"),
    Option("count", "int", 8, "Rows", minimum=1, maximum=12),
    Option("quantity", "bool", True, "Show quantity"),
])
def render_top_items(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    items = sorted(ctx.data.snapshot.items, key=lambda i: i.value, reverse=True) if ctx.data.snapshot else []
    if not items:
        empty(ctx, box, "No data yet")
        return
    for row, item in zip(rows(box, o["count"]), items):
        f = font("Inter", int(min(18, max(10, row.h * 0.52))), 500)
        vf = font("Inter", f.size, 700)
        value = fmt_amount(item.value)
        icon = int(f.size * 0.85)
        vw = text_size(value, vf)[0]
        right = row.x + row.w - icon - 4
        draw.divine_icon(ctx, right + 4, row.y + (row.h - icon) / 2, icon)
        draw.text_in(ctx, Box(right - vw, row.y, vw, row.h), value, vf, WHITE, "right")
        name_right = right - vw - 10
        if o["quantity"]:
            qty = f"×{item.quantity:,}"
            qw = text_size(qty, f)[0]
            draw.text_in(ctx, Box(name_right - qw, row.y, qw, row.h), qty, f, MUTED, "right")
            name_right -= qw + 8
        name = draw.truncate(item.name, f, name_right - row.x)
        draw.text_in(ctx, Box(row.x, row.y, name_right - row.x, row.h), name, f, WHITE, "left")


@widget("tab_totals", "Stash tabs", "Value of each stash tab, with bars.", [
    Option("title", "text", "Tabs", "Title"),
    Option("count", "int", 8, "Rows", minimum=1, maximum=12),
    Option("bars", "bool", True, "Show bars"),
])
def render_tab_totals(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    tabs = sorted(ctx.data.tabs(), key=lambda t: t.value, reverse=True)
    if not tabs:
        empty(ctx, box, "No data yet")
        return
    top = tabs[0].value or 1.0
    for row, tab in zip(rows(box, o["count"]), tabs):
        f = font("Inter", int(min(18, max(10, row.h * 0.52))), 500)
        vf = font("Inter", f.size, 700)
        if o["bars"]:
            bw = max(4, row.w * tab.value / top)
            pad = row.h * 0.12
            draw.paint(ctx, GOLD, lambda d, r=row: d.rounded_rectangle(
                (r.x, r.y + pad, r.x + bw, r.y + r.h - pad), radius=3, fill=255), alpha=38)
        value = fmt_amount(tab.value)
        vw = text_size(value, vf)[0]
        draw.text_in(ctx, Box(row.x + row.w - vw - 6, row.y, vw, row.h), value, vf, WHITE, "right")
        name = draw.truncate(tab.name, f, row.w - vw - 22)
        draw.text_in(ctx, Box(row.x + 6, row.y, row.w - vw - 22, row.h), name, f, WHITE, "left")


@widget("item_price", "Item prices", "Prices of chosen items from poe.ninja.", [
    Option("title", "text", "Prices", "Title"),
    Option("items", "items", ["Mirror of Kalandra"], "Items"),
    Option("unit", "choice", "div", "Unit", choices=["div", "chaos"]),
    Option("change", "bool", True, "Show 7-day change"),
])
def render_item_price(ctx: Ctx, box: Box, o: dict) -> None:
    box = list_title(ctx, box, o["title"])
    names = o["items"] or []
    if not names:
        empty(ctx, box, "No items chosen")
        return
    for row, name in zip(rows(box, max(len(names), 3)), names):
        f = font("Inter", int(min(20, max(10, row.h * 0.5))), 500)
        vf = font("Inter", f.size, 700)
        price = ctx.data.item_prices.get(name)
        if price is None:
            value, change = "--", None
        elif o["unit"] == "div" and price.div is not None:
            value, change = fmt_amount(price.div), price.change
        else:
            value, change = f"{price.chaos:,.0f}c", price.change
        right = row.x + row.w
        if o["change"] and change is not None:
            ct = f"{change:+.0f}%"
            cw = text_size(ct, f)[0]
            draw.text_in(ctx, Box(right - cw, row.y, cw, row.h), ct, f, signed_color(change), "right")
            right -= cw + 10
        icon = int(f.size * 0.85) if o["unit"] == "div" and price and price.div is not None else 0
        if icon:
            draw.divine_icon(ctx, right - icon, row.y + (row.h - icon) / 2, icon)
            right -= icon + 4
        vw = text_size(value, vf)[0]
        draw.text_in(ctx, Box(right - vw, row.y, vw, row.h), value, vf, WHITE, "right")
        label = draw.truncate(name, f, right - vw - 10 - row.x)
        draw.text_in(ctx, Box(row.x, row.y, right - vw - 10 - row.x, row.h), label, f, WHITE, "left")


@widget("stack_value", "Stack or tab", "The value of one item stack or one stash tab.", [
    Option("match", "choice", "item", "Look up", choices=["item", "tab"]),
    Option("name", "text", "Divine Orb", "Item or tab name"),
    Option("label", "text", "", "Label (empty = the name)"),
    Option("icon", "bool", True, "Divine icon"),
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
            value, sub = item.value, f"×{item.quantity:,}"
    value_block(
        ctx, box, label=o["label"] or o["name"], main=fmt_amount(value) if value is not None else "--",
        sub=sub, color=color_for(o["color"], ctx.data, None), sub_color=MUTED, icon=o["icon"],
        family=o["font"], weight=o["weight"], align=o["align"],
    )


@widget("text", "Text", "Free text. Placeholders like {total}, {rate}, {league}, {time} are filled in.", [
    Option("text", "text", "{league}", "Text"),
    Option("size", "int", 0, "Size (0 = fit the slot)", minimum=0, maximum=120),
    Option("align", "choice", "left", "Alignment", choices=["left", "center", "right"]),
    *_font_options(weight=500, color=MUTED),
])
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
    Option("align", "choice", "center", "Alignment", choices=["left", "center", "right"]),
    *_font_options(color=WHITE),
])
def render_clock(ctx: Ctx, box: Box, o: dict) -> None:
    now = datetime.fromtimestamp(ctx.data.now).astimezone()
    main = now.strftime("%H:%M") if o["hours"] == "24h" else now.strftime("%I:%M %p").lstrip("0")
    value_block(
        ctx, box, label="", main=main, sub=now.strftime("%A %d %B") if o["date"] else "",
        color=color_for(o["color"], ctx.data, None), sub_color=MUTED, icon=False,
        family=o["font"], weight=o["weight"], align=o["align"],
    )


def faint_frame(ctx: Ctx, box: Box) -> None:
    """Outline of an empty slot (used by the builder preview)."""
    draw.paint(ctx, FAINT, lambda d: d.rounded_rectangle((box.x, box.y, box.x + box.w, box.y + box.h), radius=6, outline=255, width=1))
