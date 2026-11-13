"""poe.ninja prices for the item-price card (docs/SCOPE.md §6).

Only the lists that hold an item chosen in a card are fetched, at most every `poeninja.interval`
seconds (30 min by default) each, with the descriptive User-Agent of AssetCache and the ETag of
the last answer. Prices are kept on disk, so a restart does not fetch again. Which list an item is
on comes from the weekly icon index (AssetCache.kind).

Two answer shapes:
- exchange lists (currency, scarabs, cards...): `lines[]` with `id`, `primaryValue` (chaos) and
  `sparkline.totalChange`, and `items[]` mapping each `id` to its `name`
- item lists (uniques, maps, gems): `lines[]` with `name`, `chaosValue` and `sparkLine.totalChange`
"""

import json
import logging
import time
from pathlib import Path

import requests

from ..assets import NINJA, AssetCache
from ..render.data import ItemPrice

log = logging.getLogger(__name__)


def parse(payload: dict) -> dict[str, tuple[float, float | None]]:
    """Lower-case item name -> (chaos, 7-day change in %), from either answer shape."""
    names = {i.get("id"): i.get("name") for i in payload.get("items", []) if i.get("id")}
    out: dict[str, tuple[float, float | None]] = {}
    for line in payload.get("lines", []):
        name = line.get("name") or names.get(line.get("id"))
        chaos = line.get("chaosValue", line.get("primaryValue"))
        if not name or chaos is None:
            continue
        spark = line.get("sparkLine") or line.get("sparkline") or {}
        out[name.lower()] = (float(chaos), spark.get("totalChange"))
    return out


class Prices:
    def __init__(self, assets: AssetCache, interval: float = 1800):
        self.assets = assets
        self.interval = interval
        self.path: Path = assets.root / "prices.json"
        try:
            self.lists: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.lists = {}  # "endpoint|type|league" -> {"fetched", "etag", "prices": {name: [chaos, change]}}

    def refresh(self, names: list[str], league: str, now: float | None = None) -> None:
        """Fetch the lists these items are on, when older than the interval. Run off the drawing path."""
        now = time.time() if now is None else now
        wanted = {self.assets.kind(n) for n in names} - {None}
        changed = False
        for endpoint, kind in sorted(wanted):
            key = f"{endpoint}|{kind}|{league}"
            entry = self.lists.get(key, {})
            if now - entry.get("fetched", 0) < self.interval or self.assets.offline:
                continue
            headers = {"If-None-Match": entry["etag"]} if entry.get("etag") else {}
            try:
                r = self.assets.http.get(f"{NINJA}/{endpoint}/overview", params={"league": league, "type": kind},
                                         headers=headers, timeout=30)
            except requests.RequestException as e:
                log.info("poe.ninja %s: %s", kind, type(e).__name__)
                continue
            if r.status_code == 304:
                entry["fetched"] = now
            elif r.ok:
                try:
                    found = parse(r.json())
                except (AttributeError, TypeError, ValueError) as e:  # not the JSON expected
                    log.info("poe.ninja %s: unreadable answer (%s)", kind, type(e).__name__)
                    continue
                entry = {"fetched": now, "etag": r.headers.get("etag"), "prices": found}
            else:
                log.info("poe.ninja %s: HTTP %s", kind, r.status_code)
                continue
            self.lists[key] = entry
            changed = True
        if changed:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.lists), encoding="utf-8")

    def get(self, names: list[str], league: str, div_price: float | None) -> dict[str, ItemPrice]:
        """The prices known for these items, as the card shows them. Never fetches."""
        out = {}
        for name in names:
            kind = self.assets.kind(name)
            entry = self.lists.get(f"{kind[0]}|{kind[1]}|{league}") if kind else None
            found = (entry or {}).get("prices", {}).get(name.lower())
            if found:
                chaos, change = found
                out[name] = ItemPrice(chaos=chaos, div=chaos / div_price if div_price else None, change=change)
        return out
