import time

import pytest

from stashdisplay import pages as pagelib
from stashdisplay.cli import demo_render_data
from stashdisplay.history import History
from stashdisplay.render import data as renderdata
from stashdisplay.render import renderer
from stashdisplay.render.templates import TEMPLATES
from stashdisplay.render.theme import DOTS_TOP, HEIGHT, WIDTH
from stashdisplay.render.fonts import NAME_FAMILY, font, text_size
from stashdisplay.render.widgets import WIDGETS, fill_placeholders, note_lines

NOW = time.time()


@pytest.fixture(scope="module")
def demo():
    return demo_render_data(NOW, seed=1)


@pytest.fixture(scope="module")
def no_data():
    return renderdata.build(History(path=None), None, now=NOW, synced_at=None)


def test_preset_pages_render(demo):
    shown = pagelib.visible(pagelib.preset())
    assert [p["id"] for p in shown] == ["total", "top", "session"]
    for i, page in enumerate(shown):
        img = renderer.preview(page, demo, i, len(shown))
        assert img.size == (WIDTH, HEIGHT)


@pytest.mark.parametrize("template", list(TEMPLATES))
@pytest.mark.parametrize("widget", list(WIDGETS))
def test_every_widget_fits_every_slot(template, widget, demo, no_data):
    page = pagelib.normalize_page({
        "template": template,
        "slots": {slot: {"widget": widget} for slot in TEMPLATES[template].slots},
    })
    for data in (demo, no_data):
        overlay = renderer.overlay(page, data)
        # The strip at the bottom belongs to the screen's pagination dots.
        assert overlay.crop((0, DOTS_TOP, WIDTH, HEIGHT)).getextrema()[3] == (0, 0)


def test_templates_stay_on_screen():
    for t in TEMPLATES.values():
        for box in t.slots.values():
            assert box.x >= 0 and box.y >= 0
            assert box.x + box.w <= WIDTH and box.y + box.h <= DOTS_TOP


def test_normalize_fills_defaults_and_drops_junk():
    page = pagelib.normalize_page({
        "template": "split",
        "slots": {
            "col1": {"widget": "top_items", "count": "99"},
            "col2": {"widget": "does-not-exist"},
            "main": {"widget": "value"},  # not a slot of this template
        },
        "background": {"kind": "hologram"},
    })
    assert page["slots"]["col1"]["count"] == 12  # clamped to the maximum
    assert page["slots"]["col1"]["quantity"] is True
    assert page["slots"]["col2"] is None
    assert set(page["slots"]) == {"col1", "col2"}
    assert page["background"] == {"kind": "color", "value": "#000000", "fit": "cover", "x": 50, "y": 50}
    assert page["header"] == {"title": True, "clock": True, "synced": True}


def test_widget_defaults_are_not_shared():
    a = pagelib.normalize_slot({"widget": "item_price"})
    a["items"].append("Headhunter")
    assert pagelib.normalize_slot({"widget": "item_price"})["items"] == ["Mirror of Kalandra"]


def test_note_lines_wrap_and_bullets():
    f = font(NAME_FAMILY, 20)
    lines = note_lines(["- " + "word " * 30, "", "plain"], f, 200)
    bullets = [b for b, _, _ in lines]
    assert bullets[0] is True and not any(bullets[1:])  # only the first line of a bullet gets the dot
    wrapped = [(t, i) for b, t, i in lines if t and t != "plain"]
    assert len(wrapped) > 1 and all(i > 0 for _, i in wrapped)  # continuation lines stay indented
    assert all(text_size(t, f)[0] <= 200 - i for t, i in wrapped)
    assert ("", 0) in [(t, i) for _, t, i in lines]  # the blank line is kept
    assert lines[-1] == (False, "plain", 0)


def test_long_note_is_cut_not_overflowing(demo):
    page = pagelib.normalize_page({"template": "full", "slots": {"main": {"widget": "notes", "text": "line\n" * 200}}})
    overlay = renderer.overlay(page, demo)
    assert overlay.crop((0, DOTS_TOP, WIDTH, HEIGHT)).getextrema()[3] == (0, 0)


def test_placeholders(demo):
    text = fill_placeholders("{league} {rate} {unknown}", demo)
    assert text.startswith("Demo ")
    assert text.endswith("/h {unknown}")


def test_formatting():
    assert renderdata.fmt_metric("div", 239.94) == "239.9"
    assert renderdata.fmt_metric("div", 3.456) == "3.46"
    assert renderdata.fmt_metric("signed", -2.5) == "-2.50"
    assert renderdata.fmt_metric("rate", 3.8) == "+3.80/h"
    assert renderdata.fmt_metric("chaos", 215.4) == "215c"
    assert renderdata.fmt_metric("div", 12345) == "12.3k"
    assert renderdata.fmt_metric("div", None) == "--"
    assert renderdata.fmt_duration(30) == "now"
    assert renderdata.fmt_duration(130) == "2m"
    assert renderdata.fmt_duration(2 * 3600 + 300) == "2h05"
