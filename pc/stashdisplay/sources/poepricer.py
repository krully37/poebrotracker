"""PoE Pricer (MDero/poe-pricer, the friends' pricer): a local app with its own HTTP API.

It runs on 127.0.0.1:5175 by default, or on another machine (`poepricer.url` in the settings).
Its API needs no login. What is used here (docs/SCOPE.md §6 and §9):
- `GET /api/ping` → {"app": "poe-pricer"}: is it there
- `GET /api/wealth/families?league=&hours=` → the bulk items' value per family (Currency, Scarab,
  DivinationCard...), in chaos (`series[].last` is now)
- `GET /api/wealth?league=&hours=` → each tab's value, in chaos: only its unique tabs are used
- `GET /api/rates?league=` → {"divineToChaos"}: the divine price, the first source for it
The total is the bulk items plus the uniques; rares and gear are left out, too hard to price
(owner, 2026-10-29). Only reads: nothing here asks it to price, scan or refresh anything.
"""

import time

import requests

from .base import Item, Snapshot, SourceError, Tab

DEFAULT_URL = "http://127.0.0.1:5175"
TIMEOUT = 5
UNAVAILABLE = "PoE Pricer unavailable"


def _get(base: str, path: str, params: dict | None = None, session=None, timeout: float = TIMEOUT) -> dict:
    try:
        r = (session or requests).get(base.rstrip("/") + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise SourceError(UNAVAILABLE, type(e).__name__) from e


def running(base: str = DEFAULT_URL, session=None) -> bool:
    try:
        return _get(base, "/api/ping", session=session, timeout=1.5).get("app") == "poe-pricer"
    except (SourceError, AttributeError):  # not there, or something else answering on that port
        return False


def divine_price(league: str, base: str = DEFAULT_URL, session=None) -> float | None:
    """Chaos per divine, or None when PoE Pricer is not there or does not know."""
    try:
        rate = float(_get(base, "/api/rates", {"league": league}, session).get("divineToChaos") or 0)
    except (SourceError, AttributeError, TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def is_unique_tab(name: str, words: str) -> bool:
    """A tab of uniques, by its name: it holds one of `words` (comma-separated, any case)."""
    return any(w.strip().lower() in name.lower() for w in words.split(",") if w.strip())


# Items that count, like the total: priced bulk items anywhere, uniques only in unique tabs. Rares,
# magic items and gems are too hard to price; the character's equipment is not stash wealth.
_NOT_BULK = {"Rare", "Magic", "Gem", "Unique"}


def counts(item: dict, in_unique_tab: bool) -> bool:
    # /api/items also lists what has left the tab ("gone"), for its own interface.
    if item.get("gone") or item.get("status") != "priced" or not item.get("chaos") or item.get("tabId", "").startswith("character"):
        return False
    return item.get("rarity") == "Unique" if in_unique_tab else item.get("rarity") not in _NOT_BULK


def fetch(league: str, base: str = DEFAULT_URL, session=None, now: float | None = None,
          unique_tabs: str = "unique") -> Snapshot:
    """The stash as PoE Pricer last read it, in divines: one entry per bulk family, plus each tab
    of uniques. PoE Pricer gives no tab types, so unique tabs are found by name. The items (for the
    most valuable ones) follow the same rule, one request per tab: it is a local app, and these
    reads cost it no GGG quota. An answer shaped another way than expected reads as unavailable."""
    try:
        return _fetch(league, base, session, now, unique_tabs)
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise SourceError(UNAVAILABLE, f"unexpected {type(e).__name__}") from e


def _fetch(league: str, base: str, session, now: float | None, unique_tabs: str) -> Snapshot:
    now = time.time() if now is None else now
    rate = divine_price(league, base, session)
    if not rate:
        raise SourceError(UNAVAILABLE, "no divine price")
    params = {"league": league, "hours": 24}
    families = _get(base, "/api/wealth/families", params, session).get("series", [])
    tabs = [Tab(s.get("type", "?"), float(s.get("last") or 0) / rate) for s in families]
    items = []
    for s in _get(base, "/api/wealth", params, session).get("series", []):
        unique = is_unique_tab(s.get("name") or "", unique_tabs)
        if unique:
            tabs.append(Tab(s["name"], float(s.get("last") or 0) / rate))
        rows = _get(base, "/api/items", {"league": league, "tabId": s.get("tabId", "")}, session).get("items", [])
        items += [Item(i.get("name", "?"), int(i.get("stackSize") or 1), float(i["chaos"]) / rate, s.get("name", ""))
                  for i in rows if counts(i, unique)]
    return Snapshot(total=sum(t.value for t in tabs), time=now, items=items, tabs=tabs, div_price=rate, league=league)
