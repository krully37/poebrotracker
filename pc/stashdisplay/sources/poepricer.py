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

from .base import Snapshot, SourceError, Tab

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
    except SourceError:
        return False


def divine_price(league: str, base: str = DEFAULT_URL, session=None) -> float | None:
    """Chaos per divine, or None when PoE Pricer is not there or does not know."""
    try:
        rate = _get(base, "/api/rates", {"league": league}, session).get("divineToChaos")
    except SourceError:
        return None
    return float(rate) if rate and rate > 0 else None


def is_unique_tab(name: str, words: str) -> bool:
    """A tab of uniques, by its name: it holds one of `words` (comma-separated, any case)."""
    return any(w.strip().lower() in name.lower() for w in words.split(",") if w.strip())


def fetch(league: str, base: str = DEFAULT_URL, session=None, now: float | None = None,
          unique_tabs: str = "unique") -> Snapshot:
    """The stash as PoE Pricer last read it, in divines: one entry per bulk family, plus each tab
    of uniques. PoE Pricer gives no tab types, so unique tabs are found by name. No items: its
    item list is per tab and is left for later."""
    now = time.time() if now is None else now
    rate = divine_price(league, base, session)
    if not rate:
        raise SourceError(UNAVAILABLE, "no divine price")
    params = {"league": league, "hours": 24}
    families = _get(base, "/api/wealth/families", params, session).get("series", [])
    tabs = [Tab(s.get("type", "?"), float(s.get("last") or 0) / rate) for s in families]
    for s in _get(base, "/api/wealth", params, session).get("series", []):
        if is_unique_tab(s.get("name") or "", unique_tabs):
            tabs.append(Tab(s["name"], float(s.get("last") or 0) / rate))
    return Snapshot(total=sum(t.value for t in tabs), time=now, tabs=tabs, div_price=rate, league=league)
