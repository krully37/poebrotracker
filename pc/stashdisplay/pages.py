"""Page definitions: what the settings page edits and the renderer draws.

A page is plain JSON so it can be saved in settings.json as is:

    {
      "id": "total", "name": "Total", "hidden": false,
      "template": "hero",
      "header": {"title": true, "clock": true, "synced": true},
      "background": {"kind": "color", "value": "#000000"},
      "slots": {"main": {"widget": "value", "metric": "total", ...}, ...}
    }

`normalize` fills in anything missing, so old or hand-edited settings keep working.
"""

import copy
import uuid

from .render import frames
from .render.templates import TEMPLATES
from .render.theme import BACKGROUND
from .render.widgets import FRAMES, WIDGETS, media_layout, slot_title, under_label

DEFAULT_HEADER = {"title": True, "clock": True, "synced": True}
DEFAULT_BACKGROUND = {"kind": "color", "value": BACKGROUND, "fit": "cover", "x": 50, "y": 50}
BACKGROUND_KINDS = ["color", "image", "gif", "video"]
BACKGROUND_FITS = ["cover", "contain"]


def normalize_slot(slot: dict | None) -> dict | None:
    if not slot or slot.get("widget") not in WIDGETS:
        return None
    wt = WIDGETS[slot["widget"]]
    out = {"widget": wt.id, "frame": slot.get("frame") if slot.get("frame") in FRAMES else wt.frame}
    for opt in wt.options:
        value = slot.get(opt.key, copy.deepcopy(opt.default))
        if opt.kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = opt.default
            if opt.minimum is not None:
                value = max(opt.minimum, value)
            if opt.maximum is not None:
                value = min(opt.maximum, value)
        elif opt.kind == "choice" and value not in opt.choices:
            value = opt.default
        out[opt.key] = value
    return out


def normalize_page(page: dict) -> dict:
    template = page.get("template") if page.get("template") in TEMPLATES else "hero"
    slots_in = page.get("slots") or {}
    background = {**DEFAULT_BACKGROUND, **(page.get("background") or {})}
    if background["kind"] not in BACKGROUND_KINDS:
        background = dict(DEFAULT_BACKGROUND)
    if background["fit"] not in BACKGROUND_FITS:
        background["fit"] = "cover"
    for axis in ("x", "y"):
        try:
            background[axis] = min(100, max(0, int(background[axis])))
        except (TypeError, ValueError):
            background[axis] = 50
    return {
        "id": str(page.get("id") or uuid.uuid4().hex[:8]),
        "name": str(page.get("name") or "Page"),
        "hidden": bool(page.get("hidden", False)),
        "template": template,
        "header": {**DEFAULT_HEADER, **(page.get("header") or {})},
        "background": background,
        # Slots that the template does not have are dropped; missing ones stay empty.
        "slots": {name: normalize_slot(slots_in.get(name)) for name in TEMPLATES[template].slots},
    }


def visible(pages: list[dict]) -> list[dict]:
    return [p for p in pages if not p["hidden"]]


# What a long press resets, by what a slot shows. Anything else is not resettable.
# Maps this session belong to the same session (docs/SCOPE.md §5c).
RESETS = {("value", "session"): "reset_session", ("value", "rate"): "reset_rate",
          ("sparkline", "session"): "reset_session", ("value", "maps_session"): "reset_session"}


def touch_zones(page: dict) -> list[dict]:
    """Areas of the page the screen reacts to: a long press resets a value ("hold", the default),
    a tap runs a media button ("gesture": "tap")."""
    zones = []
    for name, box in TEMPLATES[page["template"]].slots.items():
        slot = page["slots"].get(name)
        if not slot:
            continue
        if slot["widget"] == "media":
            if slot["buttons"]:
                # The same boxes the card draws its buttons in (renderer.overlay: frame, then title).
                inner = box if slot["frame"] == "none" else frames.content_box(box, slot["frame"] == "tooltip" and bool(slot_title(slot)))
                if slot["frame"] != "tooltip":
                    inner = under_label(inner, slot["title"])
                for action, b in media_layout(inner, slot["cover"])[2]:
                    zones.append({"x": b.x, "y": b.y, "w": b.w, "h": b.h, "action": action, "gesture": "tap"})
            continue
        shown = slot.get("metric") if slot["widget"] == "value" else slot.get("series")
        action = RESETS.get((slot["widget"], shown))
        if action:
            zones.append({"x": box.x, "y": box.y, "w": box.w, "h": box.h, "action": action})
    return zones


def preset() -> list[dict]:
    """The pages a fresh install starts with: the brief's three pages, then the maps."""
    pages = [
        {
            "id": "total", "name": "Total", "template": "hero",
            "slots": {
                "main": {"widget": "value", "metric": "total", "label": "Stash value"},
                "side": {"widget": "value", "metric": "rate", "label": "Per hour", "icon": False, "align": "right"},
                "chart": {"widget": "sparkline", "series": "total"},
                "footer": {"widget": "text", "text": "Session {session}  ·  Today {today}  ·  {league}", "color": "#8A8F98"},
            },
        },
        {
            "id": "top", "name": "Top", "template": "split",
            "slots": {
                "col1": {"widget": "top_items", "title": "Most valuable", "count": 8},
                "col2": {"widget": "tab_totals", "title": "Tabs", "count": 8},
            },
        },
        {
            "id": "session", "name": "Session", "template": "hero",
            "slots": {
                "main": {"widget": "value", "metric": "session", "label": "Session gain",
                         "sub": "since {session_since} ({session_duration})", "color": "auto"},
                "side": {"widget": "value", "metric": "div_price", "label": "Divine price",
                         "sub": "chaos per divine", "align": "right"},
                "chart": {"widget": "sparkline", "series": "session"},
                "footer": {"widget": "text", "text": "Best hour today {best_hour}  ·  Rate {rate}", "color": "#8A8F98"},
            },
        },
        {
            # The map tracker (docs/SCOPE.md §5c).
            "id": "maps", "name": "Maps", "template": "wide4",
            "slots": {
                "main": {"widget": "current_map", "title": "Current map"},
                "tile1": {"widget": "value", "metric": "maps_session", "label": "Maps", "sub": "{maps_today} today",
                          "align": "center"},
                "tile2": {"widget": "value", "metric": "maps_per_hour", "label": "Per hour", "align": "center"},
                "tile3": {"widget": "value", "metric": "map_time_avg", "label": "Average", "align": "center"},
                "tile4": {"widget": "value", "metric": "div_per_map", "label": "Per map", "align": "center"},
            },
        },
    ]
    return [normalize_page(p) for p in pages]
