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

from .render.templates import TEMPLATES
from .render.theme import BACKGROUND
from .render.widgets import WIDGETS

DEFAULT_HEADER = {"title": True, "clock": True, "synced": True}
DEFAULT_BACKGROUND = {"kind": "color", "value": BACKGROUND}
BACKGROUND_KINDS = ["color", "image", "gif", "video"]


def normalize_slot(slot: dict | None) -> dict | None:
    if not slot or slot.get("widget") not in WIDGETS:
        return None
    wt = WIDGETS[slot["widget"]]
    out = {"widget": wt.id}
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


def preset() -> list[dict]:
    """The pages a fresh install starts with: the brief's three pages plus one example custom page."""
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
                "col1": {"widget": "top_items", "title": "Top stacks", "count": 8},
                "col2": {"widget": "tab_totals", "title": "Tabs", "count": 8},
            },
        },
        {
            "id": "session", "name": "Session", "template": "hero",
            "slots": {
                "main": {"widget": "value", "metric": "session", "label": "Session gain",
                         "sub": "since {session_since} ({session_duration})", "color": "auto"},
                "side": {"widget": "value", "metric": "div_price", "label": "Divine", "align": "right"},
                "chart": {"widget": "sparkline", "series": "session"},
                "footer": {"widget": "text", "text": "Best hour today {best_hour}  ·  Rate {rate}", "color": "#8A8F98"},
            },
        },
        {
            "id": "league", "name": "League", "template": "grid4",
            "slots": {
                "top1": {"widget": "value", "metric": "league_gain", "label": "Since league start", "color": "auto"},
                "top2": {"widget": "value", "metric": "today", "label": "Today", "color": "auto"},
                "bottom1": {"widget": "value", "metric": "best_hour", "label": "Best hour", "color": "auto"},
                "bottom2": {"widget": "item_price", "title": "Prices", "items": ["Mirror of Kalandra", "Mageblood", "Headhunter"]},
            },
        },
    ]
    return [normalize_page(p) for p in pages]
