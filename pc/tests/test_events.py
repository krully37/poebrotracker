import io
import os

import pytest
from PIL import Image, ImageChops, ImageEnhance

from stashdisplay import gamelog
from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.gamelog import Characters, GameEvent, LogWatcher, parse
from stashdisplay.link import content as contentlib
from stashdisplay.link import protocol as p
from stashdisplay.link.simulator import SimRunner, SimScreen
from stashdisplay.link.transport import LoopbackPair
from stashdisplay.media import MediaStore
from stashdisplay.settings import Store

from test_link import wait_for

STAMP = "2026/10/27 19:04:11 123456789 cffb0734 [INFO Client 4242] "


def line(msg: str) -> str:
    return STAMP + msg + "\r\n"


def gif(seconds: float, color="red") -> bytes:
    frames = [Image.new("RGB", (480, 320), c) for c in (color, "black")]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=int(seconds * 500), loop=0)
    return buf.getvalue()


# --- Lines and characters ---------------------------------------------------------------------

def test_level_up_and_death_of_own_character():
    chars = Characters(None)
    assert parse(line(": Krully (Necromancer) is now level 92"), chars) == GameEvent("levelup", "Krully", 92)
    assert parse(line(": Krully has been slain."), chars) == GameEvent("death", "Krully")
    assert chars.listing() == [{"name": "Krully", "enabled": True, "class": "Necromancer", "level": 92}]


def test_party_members_and_chat_never_play():
    chars = Characters(None)
    # A party member levelled before we knew; joining the area shows it is someone else.
    assert parse(line(": Bob (Marauder) is now level 40"), chars)
    parse(line(": Bob has joined the area."), chars)
    assert parse(line(": Bob (Marauder) is now level 41"), chars) is None
    assert parse(line(": Bob has been slain."), chars) is None
    assert chars.listing() == []
    # Unknown characters' deaths, chat lines and other junk are ignored.
    assert parse(line(": Stranger has been slain."), chars) is None
    assert parse(line("Troll: Krully (Witch) is now level 100"), chars) is None
    assert parse(line("@From Troll: : Krully has been slain."), chars) is None
    assert parse("Krully (Witch) is now level 100", chars) is None


def test_unticked_character_is_ignored_and_saved(tmp_path):
    path = tmp_path / "characters.json"
    chars = Characters(path)
    parse(line(": Alt (Ranger) is now level 12"), chars)
    parse(line(": Bob has left the area."), chars)
    chars.set_enabled("Alt", False)
    again = Characters(path)
    assert again.listing()[0]["enabled"] is False and again.others == ["Bob"]
    assert parse(line(": Alt (Ranger) is now level 13"), again) is None
    assert again.listing()[0]["level"] == 13  # still tracked
    assert parse(line(": Alt has been slain."), again) is None


# --- Following the file -------------------------------------------------------------------------

def append(path, *lines, partial=""):
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.writelines(lines)
        f.write(partial)


def test_watcher_starts_at_the_end_and_follows(tmp_path):
    log_file = tmp_path / "Client.txt"
    append(log_file, line(": Krully (Witch) is now level 10"))  # old news
    events = []
    w = LogWatcher(lambda: log_file, Characters(None), events.append)
    assert w.step() and events == []
    append(log_file, line(": Krully (Witch) is now level 11"), partial=STAMP + ": Krully (Witch) is now")
    w.step()
    assert [e.level for e in events] == [11]
    append(log_file, " level 12\r\n")  # the rest of a line written in two goes
    w.step()
    assert [e.level for e in events] == [11, 12]
    assert w.status()["found"] and w.status()["last_event"]["level"] == 12


def test_watcher_rereads_a_file_that_was_emptied_or_replaced(tmp_path):
    log_file = tmp_path / "Client.txt"
    append(log_file, "x" * 5000 + "\n")
    events = []
    w = LogWatcher(lambda: log_file, Characters(None), events.append)
    w.step()
    log_file.write_text(line(": Krully (Witch) is now level 20"), encoding="utf-8")  # emptied, then written
    w.step()
    assert [e.level for e in events] == [20]

    os.remove(log_file)  # the friend deletes it
    assert w.step() is False and w.status()["found"] is False
    append(log_file, line(": Krully (Witch) is now level 21"))  # the game starts a new one
    w.step()
    assert [e.level for e in events] == [20, 21]


def test_missing_file_and_path_detection(tmp_path):
    w = LogWatcher(lambda: None, Characters(None), print)
    assert w.step() is False and w.status() == {"path": None, "found": False, "last_event": None}
    assert gamelog.find_client_log(str(tmp_path / "x.txt")) == tmp_path / "x.txt"
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text('"libraryfolders"\n{\n "0"\n {\n  "path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n }\n'
                   ' "1"\n {\n  "path"\t\t"D:\\\\Games\\\\SteamLibrary"\n }\n}\n')
    assert [str(p) for p in gamelog._library_folders(vdf)] == ["C:\\Program Files (x86)\\Steam", "D:\\Games\\SteamLibrary"]


# --- Animations ---------------------------------------------------------------------------------

def test_animation_files_and_durations(tmp_path, monkeypatch):
    monkeypatch.setattr(contentlib, "ANIM_DIR", tmp_path / "anims")
    media = MediaStore(tmp_path / "m")
    builder = contentlib.ContentBuilder(media)
    assert builder.animation("levelup") is None  # nothing made yet: the text card plays
    (tmp_path / "anims").mkdir()
    (tmp_path / "anims" / "levelup.gif").write_bytes(gif(1.0))
    file_id, f, seconds = builder.animation("levelup")
    assert file_id.startswith("anim-levelup-") and f.format == "gif" and seconds == contentlib.MIN_SECONDS
    upload = media.add("long.gif", gif(30.0, "blue"))
    file_id2, _, seconds2 = builder.animation("levelup", upload["id"])
    assert file_id2 != file_id and seconds2 == contentlib.MAX_SECONDS
    still = media.add("still.png", _png())
    assert builder.animation("death", still["id"])[2] == contentlib.STILL_SECONDS


def test_levelup_gif_plays_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(contentlib, "ANIM_DIR", tmp_path / "anims")
    (tmp_path / "anims").mkdir()
    (tmp_path / "anims" / "levelup.gif").write_bytes(gif(2.0))
    (tmp_path / "anims" / "death.gif").write_bytes(gif(4.0, "blue"))
    builder = contentlib.ContentBuilder(MediaStore(tmp_path / "m"))
    assert builder.animation("levelup")[2] == 4.0  # two loops
    assert builder.animation("death")[2] == 4.0  # once


def test_built_in_last_portal_gif(tmp_path):
    """The "run" clip: full screen, two loops of 2.5 s, small enough to share the flash."""
    builder = contentlib.ContentBuilder(MediaStore(tmp_path / "m"))
    file_id, f, seconds = builder.animation("lastportal")
    assert file_id.startswith("anim-lastportal-") and f.format == "gif" and not f.over_page
    assert seconds == 5.0 and len(f.data) < 2_000_000


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 40), "green").save(buf, "PNG")
    return buf.getvalue()


def see_through_gif() -> bytes:
    """90×160 (a portrait cutout, like the death cat): top half see-through, bottom half red,
    then blue (two different frames, or the GIF counts as a still image)."""
    frames = []
    for colour in (0, 1):
        f = Image.new("P", (90, 160), 255)
        f.putpalette([255, 0, 0, 0, 0, 255] + [0, 0, 0] * 254)
        f.paste(colour, (0, 80, 90, 160))
        frames.append(f)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=500, loop=0,
                   transparency=255, disposal=2)
    return buf.getvalue()


def test_see_through_gif_is_fitted_and_centred_on_the_bottom_edge(tmp_path):
    media = MediaStore(tmp_path / "m")
    builder = contentlib.ContentBuilder(media)
    _, f, _ = builder.animation("death", media.add("cat.gif", see_through_gif())["id"])
    assert f.over_page
    with Image.open(io.BytesIO(f.data)) as im:
        first = im.convert("RGBA")
    # Scaled to the screen's height (180×320), centred left to right: x 150 to 330.
    assert first.size == (480, 320)
    assert first.getpixel((100, 300))[3] == 0  # left of the cat: the page shows
    assert first.getpixel((400, 300))[3] == 0  # and right of it
    assert first.getpixel((240, 50))[3] == 0  # the see-through top half
    assert first.getpixel((155, 300)) == (255, 0, 0, 255)
    assert first.getpixel((325, 300)) == (255, 0, 0, 255)
    # An opaque GIF still fills the screen.
    _, opaque, _ = builder.animation("levelup", media.add("x.gif", gif(1.0))["id"])
    assert not opaque.over_page


@pytest.fixture
def screen_app(tmp_path, monkeypatch):
    monkeypatch.setattr(contentlib, "ANIM_DIR", tmp_path / "anims")
    (tmp_path / "anims").mkdir()
    (tmp_path / "anims" / "death.gif").write_bytes(gif(4.0))
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    pair = LoopbackPair()
    sim = SimScreen(pair.screen)
    runner = SimRunner(sim).start()
    app.start_link(lambda: [pair.pc] if pair.plugged else [])
    wait_for(lambda: app.link.state == "connected" and sim.pages and any(k.startswith("anim-") for k in sim.files))
    yield app, sim, pair
    app.link.stop()
    runner.close()


def test_events_play_on_the_screen(screen_app):
    app, sim, pair = screen_app
    # No level-up GIF: the text card. Death has its GIF on the screen.
    app.on_game_event(GameEvent("levelup", "Krully", 92))
    wait_for(lambda: sim.anim is not None and sim.anim[1] == "@event")
    assert sim.frame().getpixel((240, 160)) != (0, 0, 0)
    app.on_game_event(GameEvent("death", "Krully"))
    wait_for(lambda: sim.anim is not None and (sim.anim[0] or "").startswith("anim-death-"))
    # A level-up does not cut a death short.
    assert app.play_event("levelup", "Krully", 93) is False
    # Turned off in settings: nothing plays, and its file leaves the screen at the next sync.
    app.save({**app.store.settings, "events": {**app.store.settings["events"],
                                               "death": {"enabled": False, "media": ""}}}, None)
    wait_for(lambda: not any(k.startswith("anim-death") for k in sim.files))
    app._playing = None
    sim.anim = None
    app.on_game_event(GameEvent("death", "Krully"))
    assert app.link.jobs.empty() and sim.anim is None
    # Unplugged: events are dropped, not queued for later.
    pair.unplug()
    wait_for(lambda: app.link.state == "searching")
    assert app.play_event("levelup", "Krully", 94) is False


def test_last_portal_plays_from_the_map_tracker(screen_app):
    app, sim, _ = screen_app
    hideout = 'Generating level 60 area "HideoutSpace" with seed 1'
    city = 'Generating level 83 area "MapWorldsCitySquare" with seed 7'
    lines = [city] + [hideout, city] * 4  # the fifth way in: one portal left
    for line in lines[:-1]:
        app.maps.feed(f"2026/10/27 19:04:11 1 2 [DEBUG Client 4242] {line}")
    assert sim.anim is None
    app.maps.feed(f"2026/10/27 19:04:11 1 2 [DEBUG Client 4242] {lines[-1]}")
    wait_for(lambda: sim.anim is not None and sim.anim[1] == "@event")  # no GIF in this test: the card
    assert app._playing[0] == "lastportal"
    # It never cuts a death short, and it can be turned off.
    app.on_game_event(GameEvent("death", "Krully"))
    wait_for(lambda: (sim.anim[0] or "").startswith("anim-death-"))
    assert app.play_event("lastportal", "") is False
    app._playing = None
    app.save({**app.store.settings, "events": {**app.store.settings["events"],
                                               "lastportal": {"enabled": False, "media": ""}}}, None)
    app._last_portal()
    assert app._playing is None  # nothing was played


# --- Start animations: power-on, PC connects, game start ----------------------------------------

def test_game_start_line():
    chars = Characters(None)
    assert parse("2026/08/19 22:07:49 ***** LOG FILE OPENING *****\r\n", chars) == GameEvent("launch", "")
    # Typed in chat, it has the client prefix and a name: ignored.
    assert parse(line("Troll: 2026/08/19 22:07:49 ***** LOG FILE OPENING *****"), chars) is None
    assert parse(line(": ***** LOG FILE OPENING *****"), chars) is None


def test_start_animation_is_built_in_and_has_a_fixed_id(tmp_path):
    builder = contentlib.ContentBuilder(MediaStore(tmp_path / "m"))
    file_id, f, seconds = builder.animation("boot")
    assert file_id == "boot" and f.format == "gif" and seconds == 4.0  # 5 turns of the cat
    launch_id, launch, _ = builder.animation("launch")
    assert launch_id.startswith("anim-launch-") and launch.crc == f.crc


@pytest.fixture
def start_rig(tmp_path, monkeypatch):
    monkeypatch.setattr(contentlib, "ANIM_DIR", tmp_path / "anims")
    (tmp_path / "anims").mkdir()
    (tmp_path / "anims" / "start.gif").write_bytes(gif(4.0, "green"))
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    pair = LoopbackPair()
    sim = SimScreen(pair.screen)
    runner = SimRunner(sim).start()
    yield app, sim, pair
    if app.link:
        app.link.stop()
    runner.close()


def test_start_animation_plays_when_the_pc_connects(start_rig):
    app, sim, pair = start_rig
    app.start_link(lambda: [pair.pc] if pair.plugged else [])
    wait_for(lambda: sim.anim is not None and sim.anim[0] == "boot")
    # Game start uses the same cat: one copy on the screen, played from the boot file.
    assert "boot" in sim.files and not any(k.startswith("anim-launch") for k in sim.files)
    assert app.anim_files["launch"] == ("boot", 4.0, False)
    sim.anim = None
    app.on_game_event(GameEvent("launch", ""))
    wait_for(lambda: sim.anim is not None and sim.anim[0] == "boot")


def test_power_on_plays_it_once_and_the_pc_does_not_restart_it(start_rig):
    app, sim, pair = start_rig
    app.start_link(lambda: [pair.pc] if pair.plugged else [])
    wait_for(lambda: sim.anim is not None and sim.anim[0] == "boot")
    sim.anim = None
    synced = app.link.last_sync
    app.link.request_sync()
    wait_for(lambda: app.link.last_sync > synced)
    assert sim.anim is None  # a plain sync does not replay it
    # Unplugged and plugged back in: the screen plays it on its own at power-on...
    pair.unplug()
    wait_for(lambda: app.link.state == "searching")
    sim.power_cycle()
    assert sim.anim[0] == "boot"
    started = sim.anim[2]
    pair.plug()
    wait_for(lambda: app.link.state == "connected" and sim.pages)
    assert sim.anim is not None and sim.anim[2] == started  # ...and the PC leaves it alone
    # A reconnect without a power cycle (cable glitch, app restart) plays it again.
    sim.anim = None
    pair.unplug()
    wait_for(lambda: app.link.state == "searching")
    pair.plug()
    wait_for(lambda: sim.anim is not None and sim.anim[0] == "boot")


def test_screen_start_turned_off_leaves_the_screen(start_rig):
    app, sim, pair = start_rig
    events = app.store.settings["events"]
    app.save({**app.store.settings, "events": {**events, "boot": {"enabled": False, "media": ""}}}, None)
    app.start_link(lambda: [pair.pc] if pair.plugged else [])
    wait_for(lambda: app.link.state == "connected" and any(k.startswith("anim-launch") for k in sim.files))
    assert "boot" not in sim.files and sim.anim is None  # game start keeps its own copy


def test_see_through_gif_plays_over_the_dimmed_page(screen_app):
    app, sim, _ = screen_app
    upload = app.media.add("cat.gif", see_through_gif())
    app.save({**app.store.settings, "events": {**app.store.settings["events"],
                                               "death": {"enabled": True, "media": upload["id"]}}}, None)
    wait_for(lambda: app.anim_files.get("death", (None, 0, False))[2] and app.anim_files["death"][0] in sim.files)
    page = sim.frame()
    app.on_game_event(GameEvent("death", "Krully"))
    wait_for(lambda: sim.anim is not None and sim.anim[4])
    shown = sim.frame()
    # The page, dimmed, wherever the GIF is see-through; the GIF where it is not.
    dimmed = ImageEnhance.Brightness(page).enhance(p.EVENT_DIM)
    for box in ((0, 0, 150, 320), (330, 0, 480, 320), (150, 0, 330, 160)):  # the GIF: x 150 to 330, lower half
        assert max(hi for _, hi in ImageChops.difference(shown.crop(box), dimmed.crop(box)).getextrema()) <= 1
    assert shown.getpixel((240, 300)) in ((255, 0, 0), (0, 0, 255))
