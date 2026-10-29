"""Game icons and the Fontin font, downloaded on demand and cached in the user folder.

Nothing here is committed to the repo: the icons are GGG's art and Fontin's
licence forbids redistribution. Each PC fetches its own copy from the official
sources (GGG's image server via poe.ninja's links, and exljbris.com for Fontin).

poe.ninja asks for few requests and a descriptive User-Agent: the icon index
(item name -> icon URL) is refreshed at most once a week.
"""

import base64
import hashlib
import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path

import requests

from . import paths

log = logging.getLogger(__name__)

USER_AGENT = "poebrotracker/0.1 (personal desk display; https://github.com/krully37/poebrotracker)"
NINJA = "https://poe.ninja/poe1/api/economy"
CDN = "https://web.poecdn.com"
DIVINATION_CARD_ICON = f"{CDN}/image/Art/2DItems/Divination/InventoryIcon.png"
FONTIN_URL = "https://www.exljbris.com/dl/fontin2_pc.zip"
FONTIN_FILES = {"Fontin-Regular.ttf", "Fontin-Bold.ttf", "Fontin-SmallCaps.ttf", "Fontin-Italic.ttf"}
INDEX_MAX_AGE = 7 * 24 * 3600

# (endpoint, type) pairs whose responses carry icon links.
EXCHANGE_TYPES = [
    "Currency", "Fragment", "Runegraft", "AllflameEmber", "Tattoo", "Omen", "DjinnCoin", "Ducat",
    "EnshroudingCrystal", "DivinationCard", "Artifact", "Oil", "DeliriumOrb", "Scarab", "Astrolabe",
    "Fossil", "Resonator", "Essence",
]
ICON_SOURCES = [
    *(("exchange/current", t) for t in EXCHANGE_TYPES),
    ("stash/current/item", "SkillGem"),
    ("stash/current/item", "UniqueAccessory"),
    ("stash/current/item", "UniqueArmour"),
    ("stash/current/item", "UniqueWeapon"),
    ("stash/current/item", "UniqueJewel"),
    ("stash/current/item", "UniqueFlask"),
    ("stash/current/item", "Map"),
    ("stash/current/item", "UniqueMap"),
]


def art_url(url: str) -> str | None:
    """The full-size original of a `/gen/image/...` icon link (78 px instead of 47 px for currency).

    Those links embed base64 JSON like [25,14,{"f":"2DItems/Currency/X",...}];
    the same art is served at /image/Art/<f>.png.
    """
    m = re.search(r"/gen/image/([A-Za-z0-9_-]+)/", url)
    if not m:
        return None
    seg = m.group(1)
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        return f"{CDN}/image/Art/{payload[2]['f']}.png"
    except (ValueError, IndexError, KeyError, TypeError):
        return None


def _icons_from(payload: dict) -> dict[str, str]:
    """Item name -> icon URL, from any of the three poe.ninja response shapes."""
    icons: dict[str, str] = {}
    for d in payload.get("currencyDetails", []):  # stash currency overview
        if d.get("name") and d.get("icon"):
            icons.setdefault(d["name"].lower(), d["icon"])
    for d in payload.get("items", []):  # exchange overview
        if not d.get("name"):
            continue
        if d.get("image"):
            url = d["image"] if d["image"].startswith("http") else CDN + d["image"]
            icons.setdefault(d["name"].lower(), url)
        elif d.get("category") == "Cards":
            # Cards come without an image; in game they all share this inventory icon.
            icons.setdefault(d["name"].lower(), DIVINATION_CARD_ICON)
    for d in payload.get("lines", []):  # stash item overview
        if d.get("name") and d.get("icon"):
            icons.setdefault(d["name"].lower(), d["icon"])
    return icons


def _names_from(payload: dict) -> list[str]:
    rows = payload.get("currencyDetails", []) + payload.get("items", []) + payload.get("lines", [])
    return [r["name"] for r in rows if r.get("name")]


class AssetCache:
    def __init__(self, root: Path | None = None, offline: bool = False):
        self.root = root or paths.app_dir() / "cache"
        self.offline = offline
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        self._index: dict[str, str] | None = None
        self._names: dict[str, str] = {}
        self._kinds: dict[str, list[str]] = {}  # lower-case name -> [endpoint, type]: its poe.ninja list

    # --- Icons ---------------------------------------------------------------

    @property
    def index_path(self) -> Path:
        return self.root / "icon-index.json"

    def league(self) -> str:
        """The current softcore trade league, as poe.ninja lists it (from the cached index)."""
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8")).get("league", "")
        except (OSError, ValueError):
            return ""

    def icon_index(self) -> dict[str, str]:
        if self._index is not None:
            return self._index
        cached = {}
        if self.index_path.exists():
            cached = json.loads(self.index_path.read_text(encoding="utf-8"))
        # An index from before item prices lacks "kinds": fetch it again once.
        fresh = time.time() - cached.get("fetched", 0) < INDEX_MAX_AGE and "kinds" in cached
        if not fresh and not self.offline:
            try:
                cached = self._fetch_index()
            except requests.RequestException as e:
                log.warning("Could not refresh the icon index: %s", e)
        self._index = cached.get("icons", {})
        self._names = cached.get("names", {})
        self._kinds = cached.get("kinds", {})
        return self._index

    def kind(self, name: str) -> tuple[str, str] | None:
        """The poe.ninja list an item is on, as (endpoint, type), for its price."""
        self.icon_index()
        found = self._kinds.get(name.lower())
        return (found[0], found[1]) if found else None

    def item_names(self, query: str, limit: int = 20) -> list[str]:
        """Item names containing `query` (case-insensitive), for the settings page's item picker."""
        self.icon_index()
        q = query.strip().lower()
        if not q:
            return []
        hits = [self._names.get(k, k.title()) for k in self._index if q in k]
        hits.sort(key=lambda n: (not n.lower().startswith(q), len(n), n))
        return hits[:limit]

    def _fetch_index(self) -> dict:
        # poe.ninja lists the current softcore trade league first. Once WealthyExile is read
        # (step 7), prices follow the league it reports instead.
        league = self.http.get(f"{NINJA}/leagues", timeout=15).json()[0]["id"]
        icons: dict[str, str] = {}
        names: dict[str, str] = {}
        kinds: dict[str, list[str]] = {}
        for endpoint, kind in ICON_SOURCES:
            r = self.http.get(f"{NINJA}/{endpoint}/overview", params={"league": league, "type": kind}, timeout=30)
            if r.ok:
                payload = r.json()
                for name, url in _icons_from(payload).items():
                    icons.setdefault(name, url)
                for original in _names_from(payload):
                    names.setdefault(original.lower(), original)
                    kinds.setdefault(original.lower(), [endpoint, kind])
            time.sleep(0.5)  # be gentle: this runs about once a week
        data = {"fetched": time.time(), "league": league, "icons": icons, "names": names, "kinds": kinds}
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(data), encoding="utf-8")
        log.info("Icon index refreshed: %d items (%s)", len(icons), league)
        return data

    def icon(self, name: str) -> Path | None:
        """Local path of the item's icon, downloading it the first time. None if unknown."""
        url = self.icon_index().get(name.lower())
        if not url:
            return None
        path = self.root / "icons" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".png")
        if path.exists():
            return path
        if self.offline:
            return None
        for candidate in filter(None, (art_url(url), url)):
            try:
                r = self.http.get(candidate, timeout=15)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("Could not download the icon for %s from %s: %s", name, candidate, e)
                continue
            if r.headers.get("content-type", "").startswith("image/"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
                return path
        return None

    # --- Fontin --------------------------------------------------------------

    def fontin(self) -> dict[str, Path]:
        """Fontin files by style ('Regular', 'Bold', 'SmallCaps', 'Italic'), downloading them once."""
        folder = self.root / "fonts"
        found = {f.name for f in folder.glob("Fontin-*.ttf")} if folder.exists() else set()
        if found != FONTIN_FILES and not self.offline:
            try:
                r = self.http.get(FONTIN_URL, timeout=30)
                r.raise_for_status()
                folder.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    for member in z.namelist():
                        name = Path(member).name
                        if name in FONTIN_FILES:
                            (folder / name).write_bytes(z.read(member))
            except (requests.RequestException, zipfile.BadZipFile) as e:
                log.warning("Could not download Fontin: %s", e)
        return {
            re.sub(r"^Fontin-|\.ttf$", "", f.name): f
            for f in (folder.glob("Fontin-*.ttf") if folder.exists() else [])
        }
