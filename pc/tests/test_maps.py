import time
from datetime import datetime

import pytest

from stashdisplay.gamelog import Characters, LogWatcher, parse
from stashdisplay.maps import PAUSE_AFTER, MapTracker, area_kind, demo_stats, tier

# Made-up lines in the game's format.
DEBUG = "2026/10/27 19:04:11 123456789 1186a886 [DEBUG Client 4242] "
INFO = "2026/10/27 19:04:11 123456789 cffb06dd [INFO Client 4242] "


def area(name: str, seed: int = 1, level: int = 83) -> str:
    return DEBUG + f'Generating level {level} area "{name}" with seed {seed}\r\n'


def say(msg: str) -> str:
    return INFO + msg + "\r\n"


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Rig:
    """A tracker on a fake clock and a fake idle time, ticked by hand."""

    def __init__(self, path=None, start: float = 1_000_000.0):
        self.clock = Clock(start)
        self.idle = 0.0
        self.chars = Characters(None)
        self.chars.levelled("Krully", "Witch", 92)  # the friend's character
        self.tracker = MapTracker.load(path, self.chars, idle_seconds=lambda: self.idle, clock=self.clock)
        self.changes, self.backs = [], []
        self.tracker.on_change = lambda: self.changes.append(self.clock.t)
        self.tracker.on_back = lambda: self.backs.append(self.clock.t)

    def feed(self, *lines: str) -> None:
        for line in lines:
            self.tracker.feed(line)

    def run(self, seconds: int) -> None:
        """Seconds go by, ticked once a second like the app's thread."""
        for _ in range(seconds):
            self.clock.t += 1
            self.tracker.tick()


@pytest.fixture
def rig():
    return Rig()


def test_area_kinds_and_tiers():
    assert area_kind("MapWorldsCitySquare") == "map"
    assert area_kind("MavenBoss") == area_kind("MapAtlasEncounter_Perandus") == area_kind("Synthesis_MapBoss") == "map"
    assert area_kind("mapsidearea") == area_kind("AbyssLeagueBoss") == area_kind("SettlersBossFallenStar") == "side"
    assert area_kind("EndGame_Labyrinth_trials_spikes") == "side"
    for town in ("HideoutSpace", "1_3_town", "KalguuranSettlersLeague", "HeistHub", "SanctumFoyer_1_1", "1_1_2",
                 "EndGame_Labyrinth_boss_1"):
        assert area_kind(town) is None, town
    assert tier(83) == "T16" and tier(68) == "T1" and tier(45) == "Level 45"


def test_new_map_vs_same_map_plus_one_portal(rig):
    rig.feed(area("HideoutSpace", level=60), area("MapWorldsCitySquare", seed=7), say(": You have entered City Square."))
    rig.feed(area("HideoutSpace", level=60), area("MapWorldsCitySquare", seed=7))  # back in through a portal
    assert len(rig.tracker.maps) == 1
    first = rig.tracker.maps[0]
    assert (first.name, first.portals, first.level) == ("City Square", 2, 83)
    rig.feed(area("HideoutSpace", level=60), area("MapWorldsCitySquare", seed=8))  # the same map, a new one
    rig.feed(area("HideoutSpace", level=60), area("MapWorldsStrand", seed=8), say(": You have entered Strand."))
    assert [(m.area, m.seed, m.portals) for m in rig.tracker.maps] == [
        ("MapWorldsCitySquare", "7", 2), ("MapWorldsCitySquare", "8", 1), ("MapWorldsStrand", "8", 1)]
    # The hideout's own "You have entered" never renames a map.
    rig.feed(area("HideoutSpace", level=60), say(": You have entered Celestial Nebula Hideout."))
    assert rig.tracker.current.name == "Strand"


def test_side_areas_join_their_map_without_a_portal(rig):
    rig.feed(area("MapWorldsSilo", seed=5), say(": You have entered Silo."))
    rig.feed(area("SettlersBossFallenStar", seed=99), say(": You have entered Starfall Crater."))
    rig.feed(area("MapWorldsSilo", seed=5), area("mapsidearea", seed=12), area("MapWorldsSilo", seed=5))
    assert len(rig.tracker.maps) == 1
    silo = rig.tracker.current
    assert (silo.name, silo.portals, silo.mechanics) == ("Silo", 1, ["Starfall", "Vaal area"])
    assert rig.backs == []  # never back in the hideout yet


def test_only_time_inside_the_map_counts(rig):
    rig.feed(area("HideoutSpace", level=60))
    rig.run(30)
    rig.feed(area("MapWorldsCitySquare"))
    rig.run(100)
    rig.feed(area("AbyssLeagueBoss", seed=3))  # a side area counts
    rig.run(20)
    rig.feed(area("MapWorldsCitySquare"), area("HideoutSpace", level=60))
    rig.run(300)  # selling in the hideout: not counted
    assert rig.tracker.current.seconds == pytest.approx(120)
    assert rig.backs == [rig.clock.t - 300]
    rig.feed(area("MapWorldsCitySquare"))
    rig.run(15)
    assert rig.tracker.current.seconds == pytest.approx(135)
    assert rig.tracker.current.portals == 2
    # A long gap between ticks (the PC asleep) is not counted either.
    rig.clock.t += 600
    rig.tracker.tick()
    assert rig.tracker.current.seconds == pytest.approx(135)


def test_timer_pauses_after_10_seconds_without_input(rig):
    rig.feed(area("MapWorldsCitySquare"))
    rig.run(60)
    for second in range(30):  # hands off the keyboard: the first 10 s still count
        rig.idle = second + 1
        rig.run(1)
    assert rig.tracker.current.seconds == pytest.approx(60 + PAUSE_AFTER - 1)
    assert rig.tracker.stats(0, rig.clock.t).current.state == "paused"
    rig.idle = 0
    rig.run(5)
    assert rig.tracker.current.seconds == pytest.approx(60 + PAUSE_AFTER - 1 + 5)
    assert rig.tracker.stats(0, rig.clock.t).current.state == "running"


def test_unknown_idle_time_never_pauses():
    r = Rig()
    r.tracker.idle_seconds = lambda: None  # not Windows
    r.feed(area("MapWorldsCitySquare"))
    r.run(40)
    assert r.tracker.current.seconds == pytest.approx(40)


def test_deaths_and_mechanics_per_map(rig):
    rig.feed(area("MapWorldsCitySquare", seed=1))
    rig.feed(say("Einhar, Beastmaster: Exile! You are a welcome omen."), say("Strange Voice: So pleased to see you."),
             say("Einhar, Beastmaster: Ready, exile?"), say(": Krully has been slain."),
             say(": Stranger has been slain."),  # someone else
             say("#Troll: Einhar, Beastmaster: fake"), say("Troll: Strange Voice: fake"))  # chat
    first = rig.tracker.current
    assert (first.deaths, first.mechanics) == (1, ["Bestiary", "Delirium"])
    rig.feed(area("HideoutSpace", level=60), say("Jun, Veiled Master: Hideout talk."), say(": Krully has been slain."))
    assert (first.deaths, first.mechanics) == (1, ["Bestiary", "Delirium"])  # not in the map
    rig.feed(area("MapWorldsStrand", seed=2), say("Vorici, Silent Brother: Hm."), say("The Maven: Show me."))
    assert rig.tracker.current.mechanics == ["Betrayal", "Maven"] and rig.tracker.current.deaths == 0
    assert first.mechanics == ["Bestiary", "Delirium"]


def test_game_restart_leaves_the_map(rig):
    rig.feed(area("MapWorldsCitySquare"))
    rig.run(10)
    rig.feed("2026/10/27 19:00:02 ***** LOG FILE OPENING *****\r\n")
    rig.run(10)
    assert rig.tracker.current.seconds == pytest.approx(10)
    assert rig.tracker.stats(0, rig.clock.t).current.state == "out"


def at(hour: int, minute: int = 0, day: int = 27) -> float:
    return datetime(2026, 10, day, hour, minute).astimezone().timestamp()


def test_session_and_day_numbers():
    r = Rig(start=at(22, 0, day=26))
    for i in range(3):  # three maps of 10 min yesterday evening
        r.feed(area("MapWorldsCitySquare", seed=i))
        r.run(600)
        r.feed(area("HideoutSpace", level=60))
    r.clock.t = at(23, 55, day=26)
    r.feed(area("MapWorldsStrand", seed=10))  # started before midnight: yesterday's
    r.run(600)
    session_start = at(23, 0, day=26)
    s = r.tracker.stats(session_start, r.clock.t)
    assert (s.session, s.today) == (1, 0)
    assert s.average is None  # the only session map is still running
    r.feed(area("HideoutSpace", level=60))
    r.clock.t = at(0, 30)
    r.feed(area("MapWorldsDunes", seed=11))
    r.run(300)
    s = r.tracker.stats(session_start, r.clock.t)
    assert (s.session, s.today) == (2, 1)
    assert s.average == pytest.approx(600)  # Strand; Dunes is still running
    assert s.per_hour == pytest.approx(2 / (r.clock.t - at(23, 55, day=26)) * 3600)
    assert r.tracker.stats(0, r.clock.t).session == 5
    # A hold on the session value starts a new session: no maps in it yet.
    s = r.tracker.stats(r.clock.t, r.clock.t)
    assert (s.session, s.per_hour, s.average) == (0, None, None)


def test_maps_per_hour_waits_for_15_minutes(rig):
    rig.feed(area("MapWorldsCitySquare", seed=1))
    rig.run(300)
    assert rig.tracker.stats(0, rig.clock.t).per_hour is None
    rig.feed(area("MapWorldsStrand", seed=2))
    rig.run(600)
    assert rig.tracker.stats(0, rig.clock.t).per_hour == pytest.approx(2 / 900 * 3600)


def test_maps_json_saved_and_loaded(tmp_path):
    path = tmp_path / "maps.json"
    r = Rig(path)
    r.feed(area("MapWorldsCitySquare", seed=1), say(": You have entered City Square."), say("Oshabi: Hello."))
    r.run(70)  # saved while running, once a minute
    r.feed(say(": Krully has been slain."), area("HideoutSpace", level=60))
    again = Rig(path)
    m = again.tracker.current
    assert (m.name, m.seed, m.deaths, m.mechanics, round(m.seconds)) == ("City Square", "1", 1, ["Harvest"], 70)
    # After a restart the same map again is one more portal, not a new map.
    again.feed(area("MapWorldsCitySquare", seed=1))
    assert len(again.tracker.maps) == 1 and again.tracker.current.portals == 2
    path.write_text("{not json", encoding="utf-8")
    assert Rig(path).tracker.maps == []


def test_card_changes_are_reported(rig):
    rig.feed(area("HideoutSpace", level=60))
    assert rig.changes == []
    rig.feed(area("MapWorldsCitySquare"), say(": You have entered City Square."), say("Niko, Master of the Depths: Hm."))
    assert len(rig.changes) == 3
    assert rig.tracker.tick() is False  # no time has passed
    rig.clock.t += 1
    assert rig.tracker.tick() is True


def test_watcher_feeds_every_line_to_the_tracker(tmp_path):
    log_file = tmp_path / "Client.txt"
    log_file.write_text("", encoding="utf-8")
    seen = []
    w = LogWatcher(lambda: log_file, Characters(None), lambda e: None, on_line=seen.append)
    w.step()
    with open(log_file, "a", encoding="utf-8", newline="") as f:
        f.write(area("MapWorldsCitySquare") + say(": You have entered City Square."))
    w.step()
    assert [s.rstrip("\r") for s in seen] == [area("MapWorldsCitySquare").rstrip("\r\n"),
                                              say(": You have entered City Square.").rstrip("\r\n")]
    assert parse(area("MapWorldsCitySquare"), Characters(None)) is None  # not a game event


def test_demo_stats_have_a_current_map():
    s = demo_stats()
    assert s.session and s.current and s.current.tier == "T16"


def test_app_shows_real_maps_once_there_is_one_and_resets_them_with_the_session(tmp_path):
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.settings import Store

    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    data, demo = app.render_data()
    assert demo and data.current_map.name == "City Square"  # demo maps until the first real one
    app.maps.feed(area("MapWorldsStrand", seed=4))
    app.maps.feed(say(": You have entered Strand."))
    data, demo = app.render_data()
    assert demo and data.current_map.name == "Strand" and data.metrics["maps_session"] == 1
    assert app.render_data(force_demo=True)[0].current_map.name == "City Square"
    app.on_screen_event({"type": "reset", "action": "reset_session"})
    assert app.render_data()[0].metrics["maps_session"] == 0


def test_the_timer_ticks_on_the_screen_by_resending_the_page_shown(tmp_path):
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.link import protocol as p
    from stashdisplay.link.simulator import SimRunner, SimScreen
    from stashdisplay.link.transport import LoopbackPair
    from stashdisplay.media import MediaStore
    from stashdisplay.render import renderer
    from stashdisplay.settings import Store

    from test_link import wait_for

    clock = Clock(2_000_000_000.0)
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"),
              maps=MapTracker(None, Characters(None), idle_seconds=lambda: 0, clock=clock))
    pair = LoopbackPair()
    sim = SimScreen(pair.screen)
    runner = SimRunner(sim).start()
    try:
        app.start_link(lambda: [pair.pc] if pair.plugged else [])
        wait_for(lambda: app.link.state == "connected" and "maps" in sim.overlays)
        maps_page = next(pg for pg in app.store.pages if pg["id"] == "maps")

        def rendered() -> str:
            return p.crc_hex(p.encode_overlay(renderer.overlay(maps_page, app.render_data()[0])))

        app.maps.feed(area("MapWorldsStrand", seed=4))  # a new map: a whole sync
        wait_for(lambda: sim.overlays["maps"][0] == rendered())
        before = dict(sim.overlays)
        clock.t += 1
        app._map_tick(app.maps.tick())
        time.sleep(0.3)
        assert sim.overlays == before  # the first page is shown: nothing to send
        app.link.current_page = "maps"  # the friend swiped to the Maps page
        clock.t += 1
        app._map_tick(app.maps.tick())
        wait_for(lambda: sim.overlays["maps"][0] == rendered() != before["maps"][0])
        assert {k: v for k, v in sim.overlays.items() if k != "maps"} == {k: v for k, v in before.items() if k != "maps"}
        app._map_tick(False)  # the timer did not move (paused): nothing is sent
    finally:
        app.link.stop()
        runner.close()


def test_wealthyexile_sync_after_a_map_never_more_than_once_in_5_minutes(tmp_path, monkeypatch):
    from stashdisplay import app as applib
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.settings import Store
    from stashdisplay.sources import poepricer, wealthyexile
    from stashdisplay.sources.base import Snapshot

    syncs = []
    monkeypatch.setattr(wealthyexile, "sync", lambda cookie: syncs.append(now[0]))
    monkeypatch.setattr(wealthyexile, "fetch", lambda cookie, t: Snapshot(total=40.0, time=t, league="L", div_price=300.0))
    monkeypatch.setattr(poepricer, "running", lambda url: False)
    monkeypatch.setattr(applib, "SYNC_WAIT", 0.0)
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"),
              maps=MapTracker(None, Characters(None), idle_seconds=lambda: 0))
    app.store.cookie = "a=b"
    app.store.settings["poeninja"]["enabled"] = False
    now = [10_000.0]

    def one_map(seed: int) -> None:
        app.maps.feed(area("MapWorldsCitySquare", seed=seed))
        app.maps.feed(area("HideoutSpace", level=60))

    def run_until(t: float) -> None:
        while now[0] < t:  # the fetcher's turn, every 5 s
            now[0] += 5
            app._fetch_turn(False, now[0])

    one_map(1)
    run_until(10_005)
    assert syncs == [10_005]  # straight after the map
    one_map(2)  # a quick map: the sync waits for 5 minutes since the last one
    run_until(10_200)
    one_map(3)
    run_until(10_900)
    assert syncs == [10_005, 10_305]  # one sync for maps 2 and 3, nothing more without a new map
    one_map(4)
    app.maps.feed(area("HideoutSpace", level=60))  # hideout to hideout: not after a map
    run_until(11_000)
    assert syncs == [10_005, 10_305, 10_905]
    assert all(b - a >= applib.MAP_SYNC_EVERY for a, b in zip(syncs, syncs[1:]))
    # A tap syncs too, and counts: the map's sync then waits 5 minutes after it.
    now[0] = 11_300.0
    app._fetch_turn(True, now[0])
    one_map(5)
    run_until(11_595)
    assert syncs[-1] == 11_300.0
    run_until(11_600)
    assert syncs[-1] == 11_600
    # Turned off in settings: no sync after a map.
    app.store.settings["maps"]["sync_after_map"] = False
    one_map(6)
    run_until(13_000)
    assert syncs[-1] == 11_600
