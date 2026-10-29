"""poe.ninja prices for the item-price card: both answer shapes, ETags, and only what a card needs."""

import json

from stashdisplay.assets import AssetCache
from stashdisplay.sources import ninja

EXCHANGE = {"core": {}, "lines": [{"id": "divine", "primaryValue": 200.0, "sparkline": {"totalChange": 5.5}}],
            "items": [{"id": "divine", "name": "Divine Orb"}]}
ITEMS = {"lines": [{"name": "Mageblood", "chaosValue": 40000.0, "divineValue": 200.0, "sparkLine": {"totalChange": -3}}]}


class Reply:
    def __init__(self, status, body=None, etag=None):
        self.status_code, self.ok, self.body = status, status < 400, body
        self.headers = {"etag": etag} if etag else {}

    def json(self):
        return self.body


class Http:
    def __init__(self):
        self.asked = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.asked.append((url.split("/economy/")[1], params["type"], (headers or {}).get("If-None-Match")))
        if (headers or {}).get("If-None-Match"):
            return Reply(304)
        return Reply(200, EXCHANGE if params["type"] == "Currency" else ITEMS, etag=f"e-{params['type']}")


def assets(tmp_path):
    a = AssetCache(root=tmp_path, offline=False)
    (tmp_path / "icon-index.json").write_text(json.dumps({
        "fetched": 9e12, "league": "Allflame", "icons": {}, "names": {},
        "kinds": {"divine orb": ["exchange/current", "Currency"], "mageblood": ["stash/current/item", "UniqueAccessory"]},
    }), encoding="utf-8")
    a.http = Http()
    return a


def test_both_answer_shapes():
    assert ninja.parse(EXCHANGE) == {"divine orb": (200.0, 5.5)}
    assert ninja.parse(ITEMS) == {"mageblood": (40000.0, -3)}


T = 1_800_000_000.0  # a real clock: nothing fetched yet counts as long ago


def test_fetches_only_the_lists_needed_at_most_every_interval_with_etags(tmp_path):
    a = assets(tmp_path)
    prices = ninja.Prices(a, interval=1800)
    prices.refresh(["Mageblood", "Unknown Thing"], "Allflame", now=T)
    assert a.http.asked == [("stash/current/item/overview", "UniqueAccessory", None)]
    got = prices.get(["Mageblood", "Divine Orb"], "Allflame", div_price=200)
    assert set(got) == {"Mageblood"} and got["Mageblood"].div == 200 and got["Mageblood"].change == -3
    prices.refresh(["Mageblood"], "Allflame", now=T + 1799)
    assert len(a.http.asked) == 1  # not again within 30 min
    prices.refresh(["Mageblood"], "Allflame", now=T + 1800)
    assert a.http.asked[-1] == ("stash/current/item/overview", "UniqueAccessory", "e-UniqueAccessory")  # 304
    # Kept on disk: a restart knows the price without fetching.
    again = ninja.Prices(assets(tmp_path), interval=1800)
    assert again.get(["Mageblood"], "Allflame", div_price=200)["Mageblood"].chaos == 40000.0
