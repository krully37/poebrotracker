import math

from PIL import Image

from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.idle import WAKE_SECONDS, IdleWatch
from stashdisplay.link import content as contentlib
from stashdisplay.link import protocol as p
from stashdisplay.link.client import Content, FileContent
from stashdisplay.link.simulator import SimRunner, SimScreen
from stashdisplay.link.transport import LoopbackPair
from stashdisplay.media import MediaStore
from stashdisplay.settings import Store, normalize_settings

from test_link import page, rig, wait_for  # noqa: F401 (rig is a fixture)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- When the cat shows ---------------------------------------------------------------------

def watch(idle=0.0, playing=False, **settings):
    clock, changes, state = Clock(), [], {"idle": idle, "playing": playing}
    s = {"enabled": True, "minutes": 10, **settings}
    w = IdleWatch(lambda: s, lambda: state["playing"], changes.append, lambda: state["idle"], clock)
    return w, state, clock, changes


def test_cat_after_the_minutes_without_input():
    w, state, _, changes = watch()
    state["idle"] = 9 * 60
    w.check()
    assert changes == []
    state["idle"] = 10 * 60
    w.check()
    w.check()
    assert changes == [True]  # told once, not every second
    state["idle"] = 0.5  # the mouse moved
    w.check()
    assert changes == [True, False]


def test_no_cat_while_media_plays_or_when_turned_off():
    w, state, _, changes = watch(idle=3600, playing=True)
    w.check()
    assert changes == []
    state["playing"] = False
    w.check()
    assert changes == [True]
    off, _, _, off_changes = watch(idle=3600, enabled=False)
    off.check()
    assert off_changes == []


def test_unknown_idle_time_is_never_idle():
    w, state, _, changes = watch()
    state["idle"] = None  # not Windows
    w.check()
    assert changes == []
    w.forced = True  # the simulator page's button
    w.check()
    assert changes == [True]


def test_a_touch_shows_the_pages_for_a_minute():
    w, _, clock, changes = watch(idle=3600)
    w.check()
    w.wake()
    assert changes == [True, False]
    clock.t += WAKE_SECONDS - 1
    w.check()
    assert changes == [True, False]
    clock.t += 1
    w.check()
    assert changes == [True, False, True]


def test_minutes_are_clamped():
    assert normalize_settings({"idle": {"minutes": 0}})["idle"]["minutes"] == 1
    assert normalize_settings({"idle": {"minutes": 999}})["idle"]["minutes"] == 120


# --- The sprite -----------------------------------------------------------------------------

def test_idle_sprite_is_a_small_overlay_of_the_cat(tmp_path):
    f = contentlib.ContentBuilder(MediaStore(tmp_path / "m")).idle_sprite()
    assert f.format == "sprite" and len(f.data) < 60_000
    img = p.decode_overlay(f.data)
    assert img.width == contentlib.IDLE_WIDTH and 100 < img.height < 150
    alpha = img.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0 and alpha.getpixel((img.width // 2, img.height // 2)) == 255


def sprite_file():
    img = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    img.paste((255, 200, 0, 255), (0, 10, 60, 30))  # a bar, so turning changes its outline
    return FileContent(p.encode_overlay(img), "sprite")


# --- On the screen ------------------------------------------------------------------------------

def test_cat_bounces_inside_the_screen_and_faces_where_it_goes():
    clock = Clock()
    sim = SimScreen(None, clock=clock)
    f = sprite_file()
    sim.files[p.IDLE_FILE] = {"data": f.data, "crc": f.crc, "size": len(f.data), "format": "sprite"}
    sim.last_rx = clock.t
    assert sim._set_idle(p.IDLE_FILE, clock.t) == {"ok": True}
    signs, bounces = (sim.idle["vx"] > 0, sim.idle["vy"] > 0), 0
    for _ in range(600):  # 30 s at 20 steps a second
        clock.t += 0.05
        sim.last_rx = clock.t
        sim.tick()
        left, top, right, bottom = sim._idle_extents()
        st = sim.idle
        assert 0 <= st["x"] - left + 0.5 and st["x"] + right <= 480 + 0.5
        assert 0 <= st["y"] - top + 0.5 and st["y"] + bottom <= 320 + 0.5
        now_signs = (st["vx"] > 0, st["vy"] > 0)
        bounces += now_signs != signs
        signs = now_signs
    assert bounces >= 5
    assert abs(math.hypot(sim.idle["vx"], sim.idle["vy"]) - p.IDLE_SPEED) < 1e-6  # bounces keep the speed
    # Long after the last bounce it points along its travel: upright going right.
    facing = -math.degrees(math.atan2(sim.idle["vy"], sim.idle["vx"]))
    frame = sim.frame()
    assert frame.getbbox() is not None  # the cat is drawn on black
    assert abs((sim.idle["angle"] - facing + 180) % 360 - 180) < 60
    # Without the PC, the offline screen as always.
    clock.t += p.OFFLINE_AFTER + 1
    sim.tick()
    assert sim.idle is None


def test_idle_message_needs_the_sprite_file():
    sim = SimScreen(None)
    assert sim._set_idle("idle", 0)["ok"] is False
    assert sim._set_idle(None, 0) == {"ok": True}


def test_link_shows_the_cat_and_a_touch_wakes_it(rig):
    content = Content([page("a")], {p.IDLE_FILE: sprite_file()})
    r = rig(content)
    wait_for(lambda: r.link.state == "connected" and p.IDLE_FILE in r.sim.files)
    r.link.set_idle(p.IDLE_FILE)
    wait_for(lambda: r.sim.idle is not None)
    assert r.sim.frame().getpixel((5, 5)) == (0, 0, 0)  # black around the cat, not the page
    # A tap on the cat: the pages, and the PC hears "wake" (not a refresh tap).
    r.sim.touch_down(240, 160)
    r.sim.touch_up(240, 160)
    assert r.sim.idle is None
    wait_for(lambda: r.events)
    assert r.events == [{"type": "wake", "page": "a"}]
    # Still idle after a reconnect: the PC sends it again.
    r.link.set_idle(p.IDLE_FILE)
    wait_for(lambda: r.sim.idle is not None)
    r.pair.unplug()
    wait_for(lambda: r.link.state == "searching")
    r.pair.plug()
    wait_for(lambda: r.link.state == "connected" and r.sim.idle is not None)
    r.link.set_idle(None)
    wait_for(lambda: r.sim.idle is None)


def test_app_sends_the_cat_and_wakes_on_touch(tmp_path):
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    pair = LoopbackPair()
    sim = SimScreen(pair.screen)
    runner = SimRunner(sim).start()
    try:
        app.start_link(lambda: [pair.pc] if pair.plugged else [])
        app.start_idle()
        wait_for(lambda: app.link.state == "connected" and p.IDLE_FILE in sim.files)
        sim.anim = None  # the start animation would cover the cat
        app.idle.forced = True
        app.idle.check()
        wait_for(lambda: sim.idle is not None)
        sim.touch_down(100, 100)
        sim.touch_up(100, 100)
        wait_for(lambda: not app.idle.active)
        assert sim.idle is None
        # Turned off in settings: the sprite leaves the screen.
        app.save({**app.store.settings, "idle": {"enabled": False, "minutes": 10}}, None)
        wait_for(lambda: p.IDLE_FILE not in sim.files)
    finally:
        app.idle.stop()
        app.link.stop()
        runner.close()
