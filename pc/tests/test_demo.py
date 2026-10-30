import random
import time

from stashdisplay import demo
from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.cli import demo_history
from stashdisplay.gamelog import Characters, parse
from stashdisplay.maps import MapTracker
from stashdisplay.media import MediaStore
from stashdisplay.settings import Store

from test_idle import watch


def test_the_demo_lines_take_the_real_path(tmp_path):
    now = time.time()
    demo.seed(tmp_path, now, random.Random(1))
    chars = Characters(tmp_path / "characters.json")
    tracker = MapTracker.load(tmp_path / "maps.json", chars, idle_seconds=lambda: None)
    rng, events = random.Random(2), []
    for _, step in demo.TIMELINE:
        for line in demo.log_lines(step, 95, rng):
            tracker.feed(line)
            if event := parse(line, chars):
                events.append((event.kind, event.level))
        if step == "death":
            cur = tracker.stats(0, now).current
            assert (cur.name, cur.tier, cur.state, cur.deaths, cur.mechanics) == \
                ("City Square", "T16", "running", 1, ["Bestiary"])
    assert events == [("levelup", 95), ("death", None)]
    assert tracker.stats(0, now).current.state == "out"  # back in the hideout


def test_seeded_maps_look_like_an_evening(tmp_path):
    now = time.time()
    demo.seed(tmp_path, now, random.Random(3))
    history, _, _ = demo_history(now - 130)
    tracker = MapTracker.load(tmp_path / "maps.json", Characters(tmp_path / "characters.json"))
    stats = tracker.stats(history.session_start, now)
    assert stats.session == 11
    assert stats.per_hour and 5 < stats.per_hour < 7
    assert 6 * 60 <= stats.average <= 9.5 * 60


def test_demo_step_moves_the_value_and_adds_loot(tmp_path):
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    before = app.render_data()[0]
    app.demo_step(loot=50)
    after = app.render_data()[0]
    assert after.metrics["total"] > before.metrics["total"] + 40


def test_pretend_shows_the_cat_even_just_after_a_touch():
    w, _, _, changes = watch()
    w.wake()
    w.forced = True
    w.check()
    assert changes == []  # a touch keeps the pages for a minute...
    w.pretend(True)
    assert changes == [True]  # ...but the demo shows the cat anyway
    w.pretend(False)
    assert changes == [True, False]
