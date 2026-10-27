import io
import time

import pytest
from PIL import Image

from stashdisplay import pages as pagelib
from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.cli import demo_render_data
from stashdisplay.link import protocol as p
from stashdisplay.link.client import Content, FileContent, PageContent, ScreenLink
from stashdisplay.link.simulator import SimRunner, SimScreen
from stashdisplay.link.transport import LoopbackPair
from stashdisplay.media import MediaStore
from stashdisplay.render import renderer
from stashdisplay.settings import Store


def wait_for(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    raise AssertionError("timed out")


# --- Protocol --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [0, 1, 253, 254, 255, 256, 509, 5000])
def test_cobs_round_trip(n):
    data = bytes((i * 7) % 256 if i % 5 else 0 for i in range(n))
    encoded = p.cobs_encode(data)
    assert 0 not in encoded
    assert p.cobs_decode(encoded) == data


def test_reader_resyncs_after_garbage_and_rejects_bad_crc():
    good = p.json_frame(p.PING, 1, {})
    corrupt = bytearray(p.json_frame(p.PING, 2, {}))
    corrupt[2] ^= 0x40
    reader = p.FrameReader()
    stream = b"boot log\r\n\x00" + bytes(corrupt) + good
    frames = [f for i in range(len(stream)) for f in reader.feed(stream[i:i + 1])]  # byte by byte
    assert [(f.type, f.seq) for f in frames] == [(p.PING, 1)]
    assert reader.dropped == 2


def test_overlay_codec_keeps_pixels_within_rgb565_and_4bit_alpha():
    img = renderer.overlay(pagelib.preset()[0], demo_render_data(1_700_000_000, seed=7))
    blob = p.encode_overlay(img)
    assert len(blob) < 40_000  # mostly transparent: compresses well
    back = p.decode_overlay(blob)
    for (r, g, b, a), (r2, g2, b2, a2) in zip(img.get_flattened_data()[::97], back.get_flattened_data()[::97]):
        assert abs(a - a2) <= 8
        if a2:
            assert abs(r - r2) <= 8 and abs(g - g2) <= 4 and abs(b - b2) <= 8


# --- Link against the simulated screen -----------------------------------------------------

def page(page_id, color="#102030", zones=()):
    img = Image.new("RGBA", (480, 320), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (100, 100, 200, 140))
    return PageContent(page_id, p.encode_overlay(img), {"color": color}, list(zones))


def jpeg(color):
    buf = io.BytesIO()
    Image.new("RGB", (480, 320), color).save(buf, "JPEG")
    return buf.getvalue()


class Rig:
    def __init__(self, content, flash=p.FLASH_BYTES):
        self.content = content
        self.events = []
        self.pair = LoopbackPair()
        self.sim = SimScreen(self.pair.screen, flash_bytes=flash)
        self.runner = SimRunner(self.sim).start()
        self.link = ScreenLink(lambda: [self.pair.pc] if self.pair.plugged else [],
                               lambda: self.content, self.events.append).start()

    def close(self):
        self.link.stop()
        self.runner.close()


@pytest.fixture
def rig():
    rigs = []

    def make(content, **kw):
        r = Rig(content, **kw)
        rigs.append(r)
        return r

    yield make
    for r in rigs:
        r.close()


def test_sync_pages_files_and_order(rig):
    content = Content([page("a"), page("b", zones=[{"x": 0, "y": 0, "w": 480, "h": 320, "action": "reset_session"}])],
                      {"bg-1": FileContent(jpeg("red"), "jpeg")})
    content.pages[0].bg = {"file": "bg-1", "color": "#000000"}
    r = rig(content)
    wait_for(lambda: len(r.sim.pages) == 2 and r.link.state == "connected")
    assert [pg["id"] for pg in r.sim.pages] == ["a", "b"]
    assert set(r.sim.overlays) == {"a", "b"} and "bg-1" in r.sim.files
    frame = r.sim.frame()
    assert frame.getpixel((10, 200))[0] > 200  # red JPEG background
    assert frame.getpixel((150, 120)) == (255, 255, 255)  # overlay on top

    # Only what changed is sent again; stale files are deleted.
    sent_before = r.sim.overlays["b"]
    content.pages = [page("b"), page("c", color="#ffffff")]
    content.files = {}
    r.link.request_sync()
    wait_for(lambda: [pg["id"] for pg in r.sim.pages] == ["b", "c"])
    assert r.sim.overlays["b"] == sent_before
    assert "bg-1" not in r.sim.files and "a" not in r.sim.overlays


def test_gestures_send_events(rig):
    zone = {"x": 0, "y": 40, "w": 300, "h": 120, "action": "reset_rate"}
    r = rig(Content([page("a", zones=[zone]), page("b")], {}))
    wait_for(lambda: len(r.sim.pages) == 2)
    sim = r.sim

    sim.touch_down(400, 200)
    sim.touch_up(400, 200)  # tap
    sim.touch_down(400, 200)
    sim.touch_move(300, 205)
    sim.touch_up(300, 205)  # swipe left: next page
    wait_for(lambda: len(r.events) == 2)
    assert r.events == [{"type": "tap", "page": "a"}, {"type": "page", "page": "b"}]
    assert sim.current == 1

    sim.touch_down(400, 200)
    sim.touch_move(480, 200)
    sim.touch_up(480, 200)  # swipe right: back to page a
    wait_for(lambda: sim.current == 0)
    sim.touch_down(50, 80)  # long press inside the zone
    wait_for(lambda: any(e["type"] == "reset" for e in r.events), timeout=p.PRESS_DELAY + p.RING_FILL + 2)
    sim.touch_up(50, 80)
    assert r.events[-1] == {"type": "reset", "action": "reset_rate", "page": "a"}


def test_long_press_released_early_or_outside_a_zone_does_nothing(rig):
    r = rig(Content([page("a", zones=[{"x": 0, "y": 0, "w": 100, "h": 100, "action": "reset_session"}])], {}))
    wait_for(lambda: r.sim.pages)
    r.sim.touch_down(50, 50)
    time.sleep(p.PRESS_DELAY + 0.3)
    assert r.sim.frame()  # the ring is drawn without errors
    r.sim.touch_up(50, 50)
    r.sim.touch_down(300, 300)
    time.sleep(p.PRESS_DELAY + p.RING_FILL + 0.2)
    r.sim.touch_up(300, 300)
    time.sleep(0.3)
    assert r.events == []


def test_unplug_then_reconnect_resends_nothing_already_there(rig):
    r = rig(Content([page("a")], {}))
    wait_for(lambda: r.sim.pages)
    r.pair.unplug()
    wait_for(lambda: r.link.state == "searching")
    held = dict(r.sim.overlays)
    r.pair.plug()
    wait_for(lambda: r.link.state == "connected")
    assert r.sim.overlays == held


def test_power_cycle_loses_overlays_keeps_files(rig):
    content = Content([page("a")], {"bg-1": FileContent(jpeg("blue"), "jpeg")})
    r = rig(content)
    wait_for(lambda: r.sim.pages and "bg-1" in r.sim.files)
    r.sim.power_cycle()
    assert not r.sim.pages and "bg-1" in r.sim.files
    assert r.sim.frame()  # offline screen until the PC says hello again


def test_full_flash_skips_the_background(rig):
    big = FileContent(jpeg("green") + bytes(200_000), "jpeg")
    content = Content([page("a")], {"bg-big": big})
    content.pages[0].bg = {"file": "bg-big", "color": "#334455"}
    r = rig(content, flash=100_000)
    wait_for(lambda: r.sim.pages)
    assert "bg-big" not in r.sim.files
    assert r.sim.pages[0]["bg"] == {"color": "#334455"}
    assert "space" in r.link.info["error"]


def test_screen_goes_offline_after_silence():
    now = [0.0]
    sim = SimScreen(None, clock=lambda: now[0])
    sim.handle(p.decode_frame(p.json_frame(p.HELLO, 1, {"version": 1})[:-1]))
    assert sim.online(now[0])
    now[0] = p.OFFLINE_AFTER + 1
    assert not sim.online(now[0])


def test_duplicate_frame_is_answered_not_applied_twice():
    sent = []

    class Port:
        name = "test"
        def write(self, data): sent.append(data)
        def read(self, timeout): return b""
        def close(self): pass

    sim = SimScreen(Port())
    begin = p.json_frame(p.BEGIN, 5, {"xfer": 1, "kind": "overlay", "id": "a", "size": 10, "crc": "0"})
    chunk = p.encode_frame(p.CHUNK, 6, p.chunk_payload(1, 0, b"12345"))
    for raw in (begin, chunk, chunk):
        sim.handle(p.decode_frame(raw[:-1]))
    assert len(sim.xfers[1]["buf"]) == 5
    assert sent[-1] == sent[-2]


# --- App: events change the data ------------------------------------------------------------

def test_app_tap_and_resets(tmp_path):
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    toasts = []
    app.toast = toasts.append
    data, _ = app.render_data()
    assert data.metrics["rate"] is not None
    app.on_screen_event({"type": "tap", "page": "total"})
    assert toasts == []  # the demo's last point is minutes old: refresh allowed
    app.on_screen_event({"type": "tap", "page": "total"})
    assert toasts == ["Too soon"]
    app.on_screen_event({"type": "reset", "action": "reset_rate", "page": "total"})
    data, _ = app.render_data()
    assert data.metrics["rate"] is None  # counting again from now
    app.on_screen_event({"type": "reset", "action": "reset_session", "page": "session"})
    data, _ = app.render_data()
    assert abs(data.metrics["session"]) < 1e-9
    assert toasts[-2:] == ["Div/h reset", "Session reset"]


def test_touch_zones_only_on_resettable_values():
    by_id = {pg["id"]: pagelib.touch_zones(pg) for pg in pagelib.preset()}
    assert [z["action"] for z in by_id["total"]] == ["reset_rate"]
    assert sorted(z["action"] for z in by_id["session"]) == ["reset_session", "reset_session"]
    assert by_id["top"] == []


def test_backgrounds_become_screen_files(tmp_path):
    from stashdisplay.link.content import ContentBuilder

    media = MediaStore(tmp_path / "m")
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), "purple").save(buf, "PNG")
    still = media.add("wall.png", buf.getvalue())
    frames = [Image.new("RGB", (64, 64), c) for c in ("red", "green")]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    gif = media.add("loop.gif", buf.getvalue())

    pages = pagelib.preset()[:3]
    pages[0]["background"] = {"kind": "image", "value": still["id"], "fit": "cover", "x": 50, "y": 50}
    pages[1]["background"] = {"kind": "gif", "value": gif["id"], "fit": "cover", "x": 50, "y": 50}
    pages[2]["background"] = {"kind": "image", "value": "gone", "fit": "cover", "x": 50, "y": 50}
    content = ContentBuilder(media).build(pages, demo_render_data(1_700_000_000, seed=7))

    jpeg_id, gif_id = content.pages[0].bg["file"], content.pages[1].bg["file"]
    with Image.open(io.BytesIO(content.files[jpeg_id].data)) as im:
        assert (im.format, im.size) == ("JPEG", (480, 320))
    with Image.open(io.BytesIO(content.files[gif_id].data)) as im:
        assert (im.format, im.size, im.n_frames) == ("GIF", (480, 320), 2)
    assert "file" not in content.pages[2].bg  # missing media falls back to a colour
    assert [z["action"] for z in content.pages[0].zones] == ["reset_rate"]
