"""PoE Pricer as a source, against a fake of its API (shapes from MDero/poe-pricer's src/server)."""

import pytest

from stashdisplay.sources import poepricer as pp
from stashdisplay.sources.base import SourceError


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.body


class Fake:
    """GET path -> body; records what was asked."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def get(self, url, params=None, timeout=None):
        path = url.split("5175", 1)[1]
        self.asked.append((path, params))
        if path not in self.routes:
            import requests
            raise requests.ConnectionError("refused")
        return Reply(self.routes[path])


ROUTES = {
    "/api/ping": {"app": "poe-pricer", "version": "0.12.0", "pid": 1},
    "/api/rates": {"divineToChaos": 200},
    "/api/wealth/families": {"league": "Allflame", "series": [
        {"type": "Currency", "values": [100, 3000], "last": 3000},
        {"type": "Scarab", "values": [None, 400], "last": 400},
    ]},
    "/api/wealth": {"league": "Allflame", "series": [
        {"tabId": "a1", "name": "Currency", "values": [100, 3200], "last": 3200},
        {"tabId": "b2", "name": "Sell", "values": [None, 9000], "last": 9000},  # rares: left out
        {"tabId": "c3", "name": "My Uniques", "values": [None, 200], "last": 200},
    ]},
}


def test_reads_tabs_in_divines_with_its_own_divine_price():
    fake = Fake(ROUTES)
    assert pp.running(session=fake)
    snap = pp.fetch("Allflame", session=fake, now=1000.0)
    # Bulk items by family, plus the uniques tab; the rares in "Sell" do not count.
    assert [(t.name, t.value) for t in snap.tabs] == [("Currency", 15.0), ("Scarab", 2.0), ("My Uniques", 1.0)]
    assert snap.total == pytest.approx(18.0) and snap.div_price == 200 and snap.league == "Allflame"
    assert ("/api/wealth/families", {"league": "Allflame", "hours": 24}) in fake.asked
    assert pp.fetch("Allflame", session=fake, unique_tabs="nothing, here").total == pytest.approx(17.0)


def test_unique_tabs_are_found_by_name():
    assert pp.is_unique_tab("Uniques", "unique")
    assert pp.is_unique_tab("UNIQUE stash 2", "unique")
    assert pp.is_unique_tab("Uniks", "uniks, uniques")
    assert not pp.is_unique_tab("Sell", "unique")
    assert not pp.is_unique_tab("Uniques", "")


def test_not_running_or_not_poe_pricer():
    assert not pp.running(session=Fake({}))
    assert not pp.running(session=Fake({"/api/ping": {"app": "something else"}}))
    assert pp.divine_price("Allflame", session=Fake({})) is None
    with pytest.raises(SourceError) as e:
        pp.fetch("Allflame", session=Fake({"/api/ping": ROUTES["/api/ping"]}))
    assert e.value.short == pp.UNAVAILABLE
