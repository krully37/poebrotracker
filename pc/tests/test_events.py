import io
import os

import pytest
from PIL import Image

from stashdisplay import gamelog
from stashdisplay.app import App
from stashdisplay.assets import AssetCache
from stashdisplay.gamelog import Characters, GameEvent, LogWatcher, parse
from stashdisplay.link import content as contentlib
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


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 40), "green").save(buf, "PNG")
    return buf.getvalue()


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
