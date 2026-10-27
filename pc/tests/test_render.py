import time

import pytest

from stashdisplay import pages as pagelib
from stashdisplay.cli import demo_render_data
from stashdisplay.history import History
from stashdisplay.render import data as renderdata
from stashdisplay.render import renderer
from stashdisplay.render.templates import TEMPLATES
from stashdisplay.render.theme import DOTS_TOP, HEIGHT, WIDTH
from stashdisplay.render.widgets import WIDGETS, fill_placeholders

NOW = time.time()


@pytest.fixture(scope="module")
def demo():
    return demo_render_data(NOW, seed=1)


@pytest.fixture(scope="module")
def no_data():
    return renderdata.build(History(path=None), None, now=NOW, synced_at=None)


def test_preset_pages_render(demo):
    shown = pagelib.visible(pagelib.preset())
    assert [p["id"] for p in shown] == ["total", "top", "session", "league"]
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


def test_french_numbers_durations_and_dates():
    from datetime import datetime

    from stashdisplay.render import i18n

    nb = i18n.NBSP
    assert renderdata.fmt_metric("div", 239.94, "fr") == "239,9"
    assert renderdata.fmt_metric("rate", 3.8, "fr") == "+3,80/h"
    assert renderdata.fmt_metric("chaos", 1215.4, "fr") == f"1{nb}215c"
    assert renderdata.fmt_metric("div", 12345, "fr") == "12,3k"
    assert renderdata.fmt_duration(130, "fr") == "2 min"
    assert renderdata.fmt_duration(3 * 86400, "fr") == "3 j"
    assert i18n.percent(-3, "fr") == f"-3{nb}%" and i18n.percent(7.5, "en") == "+8%"
    tuesday = datetime(2026, 10, 27, 17, 20)
    assert i18n.long_date(tuesday, "fr") == "mardi 27 octobre"
    assert i18n.short_date(tuesday, "en") == "Tue 27 Oct"


def test_every_screen_text_has_both_languages_and_a_source():
    from stashdisplay.render import i18n

    for key, (en, fr, source) in i18n.TEXT.items():
        assert en and fr, key
        assert set(source.split("+")) <= {i18n.GAME, i18n.TOOLS, i18n.STD, i18n.DRAFT}, key


def test_french_preset_and_render():
    pages = pagelib.preset("fr")
    assert [p["name"] for p in pages][-1] == "Ligue"
    assert pages[0]["slots"]["main"]["label"] == ""  # follows the metric name, in any language
    data = demo_render_data(1_700_000_000, seed=7, lang="fr")
    assert data.lang == "fr"
    for i, page in enumerate(pages):
        assert renderer.preview(page, data, i, len(pages)).size == (480, 320)
