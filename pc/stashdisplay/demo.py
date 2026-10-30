"""A short scripted show for filming the screen: `stashdisplay demo [--simulator]`.

It runs the whole app on demo data in its own folder (`<app folder>/demo`, emptied at each
start), so the real settings, history and maps are never touched. Game events go through a fake
Client.txt, the same way the simulator page's buttons do it, so they take the real path from the
log to the screen. The stash value moves by itself every few seconds; the pages are swiped by
hand while filming.

The timeline is the TIMELINE list below: change it there.
"""

import json
import os
import random
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import paths

# (seconds from the start, step). The steps are the functions in Show. Each step waits for the
# animation before it to end: the start animation lasts 4 s, the level-up 7.7 s, a death 3 s.
TIMELINE = [
    (0, "boot"),  # the start animation, then the page shown
    (5, "levelup"),
    (14, "map"),  # a new map: the Maps page's timer starts
    (19, "mechanic"),  # Einhar speaks: the map gets a Bestiary tag
    (22, "death"),
    (27, "hideout"),  # back from the map: "Syncing WealthyExile...", then the loot lands
    (32, "idle"),  # the idle cat, until the screen is touched
]
VALUE_EVERY = 3.0  # seconds between demo points: the stash value moves on its own
LOOT_DELAY = 2.0  # seconds between the sync toast and the loot showing up
LOOT = 6  # divines the map brings back

CHARACTER = ("Exile", "Witch", 94)  # name, class, level before the demo's level-up
MAP = ("MapWorldsCitySquare", "City Square", 83)  # area id, name, area level (T16)
HIDEOUT = ("HideoutSpace", "Celestial Nebula Hideout", 60)
NPC = "Einhar, Beastmaster: Exile! You are a welcome omen."
PAST_MAPS = [("MapWorldsStrand", "Strand"), ("MapWorldsDunes", "Dunes"), ("MapWorldsJungleValley", "Jungle Valley"),
             ("MapWorldsSilo", "Silo"), ("MapWorldsCrimsonTemple", "Crimson Temple"), ("MapWorldsTowerMap", "Tower")]
PAST_TAGS = ["Bestiary", "Delirium", "Betrayal", "Expedition", "Harvest", "Abyss"]


def demo_home() -> Path:
    """The demo's own folder, emptied: inside the app folder, so it is easy to find and remove."""
    home = paths.app_dir() / "demo"
    shutil.rmtree(home, ignore_errors=True)  # what cannot go (a file held open) is written over by seed()
    home.mkdir(parents=True, exist_ok=True)
    return home


def seed(home: Path, now: float, rng: random.Random) -> None:
    """What the demo starts with: the character, and the maps already run this session and today,
    so the Maps page's numbers look like an evening of mapping."""
    name, char_class, level = CHARACTER
    (home / "characters.json").write_text(json.dumps(
        {"own": {name: {"enabled": True, "class": char_class, "level": level}}, "others": []}), encoding="utf-8")
    # The demo session started a bit over 2 hours ago (cli.demo_history): 11 maps in it, 5 before.
    maps, start = [], now - 2 * 3600 - 2 * 60
    for i in range(16):
        started = start + (i - 5) * 10.5 * 60 - (20 * 60 if i < 5 else 0)
        area, title = rng.choice(PAST_MAPS)
        maps.append({"area": area, "seed": str(rng.randrange(1, 2**31)), "level": rng.choice([81, 82, 83, 83]),
                     "started": started, "name": title, "seconds": rng.uniform(6, 9.5) * 60,
                     "portals": 1 + (rng.random() < 0.2), "deaths": int(rng.random() < 0.15),
                     "mechanics": rng.sample(PAST_TAGS, rng.randint(0, 2))})
    (home / "maps.json").write_text(json.dumps({"maps": maps}), encoding="utf-8")


def log_lines(step: str, level: int, rng: random.Random) -> list[str]:
    """The Client.txt lines the game would write for a step (none for the others)."""
    now = time.strftime("%Y/%m/%d %H:%M:%S")
    info = now + " 123456789 cffb0734 [INFO Client 4242] "

    def area(area_id: str, title: str, area_level: int, area_seed: int) -> list[str]:
        return [now + f' 123456789 1186a886 [DEBUG Client 4242] Generating level {area_level} area "{area_id}"'
                f" with seed {area_seed}", info + f": You have entered {title}."]

    name, char_class, _ = CHARACTER
    return {
        "levelup": [info + f": {name} ({char_class}) is now level {level}"],
        "map": area(*MAP, rng.randrange(1, 2**31)),
        "mechanic": [info + NPC],
        "death": [info + f": {name} has been slain."],
        "hideout": area(*HIDEOUT, 1),
    }.get(step, [])


class Show:
    """Plays TIMELINE on a running app."""

    def __init__(self, app, client_log: Path, rng: random.Random):
        self.app = app
        self.client_log = client_log
        self.rng = rng
        self.level = CHARACTER[2]

    def play(self) -> None:
        self.app.idle.pretend(False)
        start = time.monotonic()
        for at, step in TIMELINE:
            time.sleep(max(0.0, start + at - time.monotonic()))
            print(f"  {at:>3} s  {step}")
            getattr(self, step)()

    def write(self, step: str) -> None:
        with open(self.client_log, "a", encoding="utf-8", newline="") as f:
            f.writelines(line + "\r\n" for line in log_lines(step, self.level, self.rng))

    def boot(self) -> None:
        self.app.play_event("boot", "", force=True)

    def levelup(self) -> None:
        self.level = min(self.level + 1, 100)
        self.write("levelup")

    def map(self) -> None:
        self.write("map")

    def mechanic(self) -> None:
        self.write("mechanic")

    def death(self) -> None:
        self.write("death")

    def hideout(self) -> None:
        from .app import SYNCING

        self.write("hideout")
        self.app.toast(SYNCING)
        time.sleep(LOOT_DELAY)
        self.app.demo_step(loot=LOOT)

    def idle(self) -> None:
        self.app.idle.pretend(True)


def wait_for_screen(app) -> None:
    """Until the screen is connected and holds every animation."""
    asked = time.monotonic()
    hinted = False
    while not (app.link.state == "connected" and app.anim_files
               and all(app.link.has_file(f) for f, _, _ in app.anim_files.values())):
        if not hinted and time.monotonic() - asked > 8:
            print("Still waiting for the screen. Is it plugged in? Quit the Stash Display app if it runs: "
                  "only one program can use the cable.")
            hinted = True
        time.sleep(0.2)


def run(offline: bool = False, simulator: bool = False) -> int:
    from .app import App
    from .cli import setup_logging

    cache = paths.app_dir() / "cache"  # the real icon and font cache: nothing downloaded again
    home = demo_home()
    os.environ["STASHDISPLAY_HOME"] = str(home)
    rng = random.Random()
    seed(home, time.time(), rng)
    setup_logging(console=False)  # the terminal only shows the demo's own lines, so the prompts stand out
    app = App.create(offline=offline, assets_root=cache)
    # The PC is left alone while filming: the map timer keeps running, and the cat waits for its step.
    app.maps.idle_seconds = lambda: None
    app.fake_log = home / "Client-demo.txt"
    app.fake_log.touch()

    if simulator:
        from .link.simulator import SimRunner, SimScreen
        from .link.transport import LoopbackPair
        from .web import server

        app.simulator = (SimScreen((pair := LoopbackPair()).screen), pair)
        SimRunner(app.simulator[0]).start()
        try:
            server.serve_in_background(app)
        except OSError:
            print("The settings port is busy: quit the Stash Display app first.")
            return 1
        app.start_link(lambda: [pair.pc] if pair.plugged else [])
        print(f"Simulated screen: the Simulator tab of {server.url(app)}")
        webbrowser.open(server.url(app))  # the demo folder's token is new at each start
    else:
        app.start_link()
    app.start_watcher()
    app.start_idle().idle_seconds = lambda: None

    print("Connecting to the screen...")
    wait_for_screen(app)

    def values() -> None:
        while True:
            time.sleep(VALUE_EVERY)
            app.demo_step()

    show = Show(app, app.fake_log, rng)
    try:
        print("\nScreen ready. Start filming, then press Enter to play the demo.")
        input("> ")
        threading.Thread(target=values, daemon=True, name="demo-values").start()
        while True:
            show.play()
            print("\nDone. Press Enter to play it again, or Ctrl+C to stop.")
            input("> ")
    except (KeyboardInterrupt, EOFError):
        print()
    if app.link:
        app.link.stop()  # closes the port without resetting the screen
    return 0


if __name__ == "__main__":
    sys.exit(run())
