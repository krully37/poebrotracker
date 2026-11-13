"""The WealthyExile reader, on a made-up page shaped like the real one (docs/SCOPE.md §9)."""

import json

import pytest

from stashdisplay.sources import wealthyexile as we
from stashdisplay.sources.base import AuthError, SourceError

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6ImZha2UifQ.c2lnbmF0dXJlLWZha2U"


@pytest.fixture(autouse=True)
def no_action_kept(monkeypatch):
    """Each test starts without a sync action remembered from another one."""
    monkeypatch.setattr(we, "_action", None)


def page(data: dict, split: int = 3) -> str:
    """An HTML page whose Next.js payload holds `data`, cut over several pushes like the real one."""
    text = "1:" + json.dumps(data, separators=(",", ":")) + "\n"
    step = len(text) // split + 1
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(text[i:i + step])}])</script>"
                     for i in range(0, len(text), step))
    return f"<html><body>{pushes}</body></html>"


def data(league="Allflame"):
    return {
        "user": {
            "username": "Someone#1234", "accessToken": "0123456789abcdef0123456789abcdef01234567",
            "preferredLeague": league, "lastSynced": "$D2026-10-29T16:26:23.000Z", "priceThresholdPerStack": 10,
            # Each tab carries its own items, as on the real page.
            "tabs": [
                {"id": 11, "name": "Currency", "tabValues": [{"value": 300, "createdAt": "$D2026-10-29T16:00:00.000Z"}],
                 "items": [{"quantity": 1500, "tabID": 11, "price": {"name": "Chaos Orb", "value": 0.2, "category": "currency"}}]},
                {"id": 12, "name": "Maps", "tabValues": [{"value": 9, "createdAt": "$D2026-10-29T16:00:00.000Z"}],
                 "items": [{"quantity": 9, "tabID": 12, "price": {"name": "Map (Tier 12)", "value": 2, "category": "maps"}},
                           # 4 chaos for the stack: under the account's 10-chaos threshold, not counted
                           {"quantity": 2, "tabID": 12, "price": {"name": "Map (Tier 1)", "value": 2, "category": "maps"}}]},
            ],
        },
        "priceMap": [
            {"name": "Divine Orb", "league": "Hardcore " + league, "value": 168.7},
            {"name": "Divine Orb", "league": league, "value": 200.0},
        ],
    }


def test_reads_league_items_and_divine_price():
    snap = we.parse(we.payload(page(data())))
    assert snap.league == "Allflame"
    assert snap.div_price == 200.0  # this league's, not hardcore's
    assert [(i.name, i.quantity, i.tab) for i in snap.items] == [("Chaos Orb", 1500, "Currency"), ("Map (Tier 12)", 9, "Maps")]
    assert snap.items[0].value == pytest.approx(1500 * 0.2 / 200)  # the stack, in divines
    assert snap.total == pytest.approx((300 + 18) / 200)  # the 4-chaos T1 stack is left out
    assert snap.time == pytest.approx(1793291183.0)  # lastSynced: when the value was true


def test_a_page_without_the_stash_says_what_went_wrong():
    with pytest.raises(AuthError):
        we.parse(we.payload(page({"user": None})))
    with pytest.raises(SourceError) as e:
        we.parse(we.payload(page({"user": {"tabs": []}, "priceMap": []})))
    assert e.value.short == we.CHANGED
    with pytest.raises(SourceError):
        we.parse(we.payload(page(data(league="Somewhere else") | {"priceMap": []})))


def test_scrub_removes_everything_that_logs_in():
    raw = we.payload(page(data())) + f'0:{{"q":"?session-Allflame-1={FAKE_JWT}","t":"{FAKE_JWT}"}}'
    clean = we.scrub(raw)
    for secret in (FAKE_JWT, "0123456789abcdef0123456789abcdef01234567", "Someone#1234"):
        assert secret not in clean
    assert '"accessToken":"<scrubbed>"' in clean and "session-Allflame-1=<scrubbed>" in clean
    assert "Map (Tier 12)" in clean  # what the parser needs stays


class Reply:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class Session:
    def __init__(self, reply):
        self.reply, self.sent = reply, None

    def get(self, url, headers, **_):
        self.sent = headers
        return self.reply


def test_fetch_sends_the_cookie_and_spots_logouts_and_cloudflare():
    s = Session(Reply(text="<html>ok</html>"))
    assert we.fetch_page("a=b", s) == "<html>ok</html>"
    assert s.sent["Cookie"] == "a=b" and "stashdisplay" in s.sent["User-Agent"]
    # Logged out, the site answers 307 to /login (seen 2026-11-13): only that, or a 401, is an expired cookie.
    for logged_out in (Reply(status=307, headers={"Location": "/login"}), Reply(status=401),
                       Reply(status=302, headers={"Location": "https://wealthyexile.com/api/auth/signin?x=1"})):
        with pytest.raises(AuthError):
            we.fetch_page("a=b", Session(logged_out))
    # Any other redirect (maintenance, another address) is tried again later, with the same cookie.
    for elsewhere in (Reply(status=307, headers={"Location": "/maintenance"}), Reply(status=308),
                      Reply(status=301, headers={"Location": "https://www.wealthyexile.com/"})):
        with pytest.raises(SourceError) as e:
            we.fetch_page("a=b", Session(elsewhere))
        assert e.value.short == we.UNAVAILABLE and not isinstance(e.value, AuthError)
    with pytest.raises(AuthError):
        we.fetch_page("", Session(Reply()))
    with pytest.raises(SourceError) as e:
        we.fetch_page("a=b", Session(Reply(status=403, headers={"cf-mitigated": "challenge"})))
    assert e.value.short == we.UNAVAILABLE


def test_app_switches_from_demo_to_wealthyexile_and_keeps_the_last_good_value(tmp_path, monkeypatch):
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.settings import Store
    from stashdisplay.sources.base import Snapshot

    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    _, demo = app.render_data()
    assert demo and not app.live
    replies = [Snapshot(total=38.6, time=1000.0, league="Allflame", div_price=337.1), SourceError(we.UNAVAILABLE)]

    def fetch(cookie, now):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(we, "fetch", fetch)
    app.store.cookie = "a=b"
    assert app.fetch(2000.0)
    data, demo = app.render_data()
    assert not demo and app.live and data.metrics["total"] == 38.6
    assert app.history.points[-1] == (1000.0, 38.6)  # timed at WealthyExile's sync, not at the read
    assert not app.fetch(2300.0)
    assert app.status["error"] == we.UNAVAILABLE
    data, demo = app.render_data()
    assert not demo and data.metrics["total"] == 38.6  # the last good value stays


def test_sync_sends_what_the_sites_button_sends():
    d = data()
    d["user"]["lastHourlySync"] = "$D2025-01-01T21:20:33.000Z"
    d["user"]["snapshots"] = [{"createdAt": "$D2026-10-29T18:00:00.000Z"}, {"createdAt": "$D2026-10-29T20:08:00.000Z"}]
    html = page(d).replace("<html>", '<html><script src="/_next/static/chunks/styles-1a2b.js?dpl=x" async=""></script><script>self.__next_f.push([1,"static/chunks/app/stash/page-9z.js"])</script>')
    action = "40" + "ab" * 20
    script = f'let n=(0,r.createServerReference)("{action}",n.callServer,void 0,n.findSourceMapURL,"syncUser")'

    class Site:
        def __init__(self):
            self.posted = None

        def get(self, url, headers=None, **_):
            return Reply(text=script if url.endswith("page-9z.js") else "" if url.endswith(".js") else html)

        def post(self, url, data, headers, **_):
            self.posted = (url, data, headers)
            return Reply(text=f'0:{{"q":"?session-x={FAKE_JWT}"}}')  # the reply can carry the session

    site = Site()
    we.sync("a=b", site)
    url, body, headers = site.posted
    assert url == we.SYNC_URL and headers["Next-Action"] == action and headers["Cookie"] == "a=b"
    # [threshold, newest snapshot, last hourly sync], dates in Next.js's "$D" form
    assert json.loads(body) == [10, "$D2026-10-29T20:08:00.000Z", "$D2025-01-01T21:20:33.000Z"]
    with pytest.raises(SourceError):
        we.sync_action("<html></html>", site)


class LandingPage:
    """The site as a visitor without the user sees it: "/" answers 200 with a page that holds no
    user at all; the stash page's own address answers as `stash` says."""

    def __init__(self, stash):
        self.stash, self.asked, self.posted = stash, [], 0

    def get(self, url, headers=None, **_):
        self.asked.append(url)
        return self.stash if url == we.STASH_URL else Reply(text=page({"plans": ["free", "premium"]}))

    def post(self, *a, **_):
        self.posted += 1
        return Reply()


def test_a_page_without_the_user_is_an_expired_cookie_when_the_stash_page_sends_to_the_login():
    """Logged out, "/" is the landing page (seen 2026-11-13): one more request tells an expired
    cookie, which stops every request, from a site that changed, which is tried again."""
    logged_out = LandingPage(Reply(status=307, headers={"Location": "/login"}))
    with pytest.raises(AuthError):
        we.fetch("a=b", session=logged_out)
    assert logged_out.asked == [we.URL, we.STASH_URL]  # the page, then the one check
    with pytest.raises(AuthError):
        we.sync("a=b", logged_out)
    assert logged_out.posted == 0  # nothing is synced with a cookie the site no longer knows

    for stash in (Reply(text="<html>the stash, shaped another way</html>"), Reply(status=503),
                  Reply(status=307, headers={"Location": "/maintenance"})):
        changed = LandingPage(stash)
        with pytest.raises(SourceError) as e:
            we.fetch("a=b", session=changed)
        assert e.value.short == we.CHANGED and not isinstance(e.value, AuthError)

    # A page that reads well asks nothing more.
    fine = LandingPage(Reply(status=307, headers={"Location": "/login"}))
    fine.get = lambda url, headers=None, **_: fine.asked.append(url) or Reply(text=page(data()))
    assert we.fetch("a=b", session=fine).league == "Allflame" and fine.asked == [we.URL]


def test_sync_reads_the_sites_scripts_once_per_deployment():
    """Polite polling: the action's id is kept with the site version, not looked up at every sync."""
    action = {"v1": "40" + "ab" * 20, "v2": "40" + "cd" * 20}

    class Site:
        def __init__(self):
            self.version, self.status, self.scripts, self.posted = "v1", 200, 0, []

        def html(self):
            return page(data()).replace("<html>", f'<html><script src="/_next/static/chunks/a-1.js?dpl={self.version}" async="">'
                                        '</script><script>self.__next_f.push([1,"static/chunks/app/stash/page-9z.js"])</script>')

        def get(self, url, headers=None, **_):
            if not url.endswith(".js"):
                return Reply(text=self.html())
            self.scripts += 1
            found = f'(0,r.createServerReference)("{action[self.version]}",n.callServer,void 0,n.findSourceMapURL,"syncUser")'
            return Reply(text=found if url.endswith("page-9z.js") else "")

        def post(self, url, data, headers, **_):
            self.posted.append(headers["Next-Action"])
            return Reply(status=self.status)

    site = Site()
    we.sync("a=b", site)
    read_once = site.scripts
    we.sync("a=b", site)
    we.sync("a=b", site)
    assert read_once == 2 and site.scripts == read_once  # both scripts once, then none
    site.version = "v2"  # the site was deployed again: its action has a new id
    we.sync("a=b", site)
    assert site.scripts == 2 * read_once and site.posted == [action["v1"]] * 3 + [action["v2"]]
    site.status = 500  # a sync turned down: the id is read again next time, in case it was the trouble
    with pytest.raises(SourceError):
        we.sync("a=b", site)
    site.status = 200
    we.sync("a=b", site)
    assert site.scripts == 3 * read_once


def test_an_expired_cookie_shows_on_the_screen_and_stops_polling_until_a_new_one(tmp_path, monkeypatch):
    """docs/SCOPE.md §6: "Cookie expired" on the screen and the tray, and no more requests to
    WealthyExile (a tap's sync included) until another cookie is saved, which is read at once."""
    from stashdisplay import app as applib
    from stashdisplay import tray
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.render import renderer
    from stashdisplay.render.theme import STALE
    from stashdisplay.settings import Store
    from stashdisplay.sources import poepricer
    from stashdisplay.sources.base import Snapshot

    calls, syncs, screen_syncs = [], [], []

    def fetch(cookie, now):
        calls.append(cookie)
        if cookie == "old=1":
            raise AuthError("Cookie expired")
        return Snapshot(total=40.0, time=now, league="L", div_price=300.0)

    monkeypatch.setattr(we, "fetch", fetch)
    monkeypatch.setattr(we, "sync", lambda cookie: syncs.append(cookie))
    monkeypatch.setattr(poepricer, "running", lambda url: False)
    monkeypatch.setattr(applib, "SYNC_WAIT", 0.0)
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    app.store.settings["poeninja"]["enabled"] = False
    app.link = type("Link", (), {"state": "connected", "request_sync": lambda self: screen_syncs.append(1)})()
    app.store.cookie = "old=1"

    app._fetch_turn(False, 10_000.0)
    assert calls == ["old=1"] and app.status["error"] == "Cookie expired"
    assert screen_syncs  # the screen is told at once, not at the next good read
    data, _ = app.render_data()
    assert data.error == "Cookie expired"
    assert renderer.sync_label(data) == ("Cookie expired", STALE)
    assert tray.status_line(app) == "Screen connected · Cookie expired"
    app.link.state = "searching"
    assert tray.status_line(app) == "Screen not connected · Cookie expired"
    app.link.state = "connected"
    assert app.render_data(force_demo=True)[0].error is None  # the settings page's demo preview

    # Hours of turns and a tap: nothing more goes to WealthyExile with that cookie.
    for t in range(10_005, 20_000, 5):
        app._fetch_turn(False, float(t))
    app.on_screen_event({"type": "tap"})
    app._fetch_turn(True, 20_000.0)
    assert calls == ["old=1"] and syncs == []

    # A new cookie is read on the next turn, without waiting for the 5 minutes.
    app.store.cookie = "new=2"
    app._fetch_turn(False, 20_005.0)
    assert calls == ["old=1", "new=2"] and app.status["error"] is None
    data, _ = app.render_data()
    assert data.error is None and renderer.sync_label(data)[0] != "Cookie expired"
    assert "Cookie expired" not in tray.status_line(app)


def test_other_read_failures_show_on_the_screen_but_polling_goes_on(tmp_path, monkeypatch):
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.settings import Store
    from stashdisplay.sources import poepricer

    calls = []

    def fetch(cookie, now):
        calls.append(now)
        raise SourceError(we.UNAVAILABLE)

    monkeypatch.setattr(we, "fetch", fetch)
    monkeypatch.setattr(poepricer, "running", lambda url: False)
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    app.store.settings["poeninja"]["enabled"] = False
    app.store.cookie = "a=b"
    app._fetch_turn(False, 10_000.0)
    assert app.render_data()[0].error == we.UNAVAILABLE
    app._fetch_turn(False, 10_000.0 + app.store.settings["interval"])
    assert len(calls) == 2  # tried again at the next turn


def test_a_surprise_in_the_page_reads_as_changed_without_quoting_it(monkeypatch):
    d = data()
    d["user"]["tabs"][0]["items"][0]["quantity"] = "secret-from-the-page"  # a text where a number was
    monkeypatch.setattr(we, "fetch_page", lambda cookie, session=None: page(d))
    with pytest.raises(SourceError) as e:
        we.fetch("a=b")
    assert e.value.short == we.CHANGED
    assert "secret-from-the-page" not in str(e.value) and e.value.__cause__ is None


def test_a_surprise_in_a_fetch_turn_is_logged_without_its_text_and_polling_goes_on(tmp_path, monkeypatch, caplog):
    """The fetcher's thread must outlive anything: a dead one only shows as "stale" for ever."""
    from stashdisplay.app import App
    from stashdisplay.assets import AssetCache
    from stashdisplay.media import MediaStore
    from stashdisplay.settings import Store
    from stashdisplay.sources import poepricer

    calls = []

    def fetch(cookie, now):
        calls.append(now)
        raise RuntimeError("secret-from-the-page")

    monkeypatch.setattr(we, "fetch", fetch)
    monkeypatch.setattr(poepricer, "running", lambda url: False)
    app = App(Store.load(tmp_path / "s.json"), AssetCache(root=tmp_path / "c", offline=True), MediaStore(tmp_path / "m"))
    app.store.settings["poeninja"]["enabled"] = False
    app.store.cookie = "a=b"
    app._guarded_turn(False, 10_000.0)  # does not raise
    assert "RuntimeError" in caplog.text and "secret-from-the-page" not in caplog.text
    app._guarded_turn(False, 10_000.0 + app.store.settings["interval"])
    assert len(calls) == 2  # tried again at the next turn
