"""The WealthyExile reader, on a made-up page shaped like the real one (docs/SCOPE.md §9)."""

import json

import pytest

from stashdisplay.sources import wealthyexile as we
from stashdisplay.sources.base import AuthError, SourceError

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6ImZha2UifQ.c2lnbmF0dXJlLWZha2U"


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
    with pytest.raises(AuthError):
        we.fetch_page("a=b", Session(Reply(status=307)))
    with pytest.raises(AuthError):
        we.fetch_page("", Session(Reply()))
    with pytest.raises(SourceError) as e:
        we.fetch_page("a=b", Session(Reply(status=403, headers={"cf-mitigated": "challenge"})))
    assert e.value.short == we.UNAVAILABLE
