"""WealthyExile (wealthyexile.com): the stash value, read from the site's own stash page.

The site has no API. Its stash page (Next.js) embeds its data in `self.__next_f.push([1, "…"])`
scripts: the user (league, last sync, tabs with their hourly values), the items with their chaos
prices, and the Divine Orb price per league (docs/SCOPE.md §6 and §9).

Its replies can carry the session itself, so nothing from here is ever logged, and `scrub()` runs
on anything written to disk (`stashdisplay dump`).
"""

import json
import re
import time
from datetime import datetime

import requests

from .base import AuthError, Item, Snapshot, SourceError

URL = "https://wealthyexile.com/"
USER_AGENT = "stashdisplay (a personal desk screen showing one stash; github.com/krully37)"
TIMEOUT = 20

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_DECODER = json.JSONDecoder()

CHANGED = "WealthyExile changed"
UNAVAILABLE = "WealthyExile unavailable"


def fetch_page(cookie: str, session: requests.Session | None = None) -> str:
    """The stash page's HTML, with the pasted Cookie header."""
    if not cookie:
        raise AuthError("No WealthyExile cookie")
    get = (session or requests).get
    try:
        r = get(URL, headers={"Cookie": cookie, "User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as e:
        raise SourceError(UNAVAILABLE, type(e).__name__) from e
    if r.headers.get("cf-mitigated") or "<title>Just a moment" in r.text[:2000]:
        # A Cloudflare check: never worked around (CLAUDE.md). The next turn tries again.
        raise SourceError(UNAVAILABLE, "Cloudflare check")
    if r.status_code in (301, 302, 303, 307, 308, 401):
        raise AuthError("Cookie expired")
    if r.status_code != 200:
        raise SourceError(UNAVAILABLE, f"HTTP {r.status_code}")
    return r.text


def payload(html: str) -> str:
    """The page's embedded data, as one string."""
    return "".join(json.loads(f'"{chunk}"') for chunk in _PUSH.findall(html))


def _values(text: str, key: str):
    """Every JSON value that follows `"key":` in the payload."""
    needle = f'"{key}":'
    at = text.find(needle)
    while at >= 0:
        try:
            value, _ = _DECODER.raw_decode(text, at + len(needle))
            yield value
        except ValueError:
            pass
        at = text.find(needle, at + len(needle))


def _first(text: str, key: str, test) -> object | None:
    return next((v for v in _values(text, key) if test(v)), None)


def _date(value: object) -> float | None:
    """Next.js writes dates as "$D2026-10-29T16:26:23.000Z"."""
    if not isinstance(value, str) or not value.startswith("$D"):
        return None
    try:
        return datetime.fromisoformat(value[2:].replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse(text: str, now: float | None = None) -> Snapshot:
    """A snapshot from the page's payload. Prices on the page are in chaos, per unit."""
    now = time.time() if now is None else now
    user = _first(text, "user", lambda v: isinstance(v, dict) and "tabs" in v)
    if user is None:
        if not text or '"user":null' in text:
            raise AuthError("Cookie expired")
        raise SourceError(CHANGED, "no user with tabs")
    league = user.get("preferredLeague") or ""
    tabs = [t for t in user.get("tabs") or [] if isinstance(t, dict)]
    prices = _first(text, "priceMap", lambda v: isinstance(v, list)) or []
    div_price = next((p.get("value") for p in prices if isinstance(p, dict)
                      and p.get("name") == "Divine Orb" and p.get("league") == league), None)
    if not div_price:
        raise SourceError(CHANGED, f"no Divine Orb price for {league!r}")
    # Like the site, stacks worth less than the account's own threshold do not count (it was 10 chaos
    # for the owner: 38.6 divines shown, against 41.2 with every stack).
    threshold = float(user.get("priceThresholdPerStack") or 0)
    items = []
    for tab in tabs:  # each tab carries its own items
        for row in tab.get("items") or []:
            price = row.get("price") if isinstance(row, dict) else None
            if not isinstance(price, dict):
                continue
            quantity = int(row.get("quantity") or 0)
            chaos = float(price.get("value") or 0) * quantity  # the page's price is per unit
            if chaos < threshold:
                continue
            items.append(Item(price.get("name", "?"), quantity, chaos / div_price, tab.get("name", "")))
    return Snapshot(total=sum(i.value for i in items), time=_date(user.get("lastSynced")) or now,
                    items=items, div_price=float(div_price), league=league)


def fetch(cookie: str, now: float | None = None) -> Snapshot:
    return parse(payload(fetch_page(cookie)), now)


# --- Sync: what the site's "Sync stash" button does -------------------------------------------
#
# A free account's values change only when it is synced (docs/SCOPE.md §6). The button calls the
# Next.js server action "syncUser" (not "syncTabs", which does not sync): POST to the stash page with
# its id in a Next-Action header and [price threshold per stack, newest snapshot's createdAt,
# user.lastHourlySync] as the body (seen 2026-10-29 in the owner's browser; changing the threshold
# to 11 changed the first value). The action's id changes with each deployment of the site, so it
# is read from the site's scripts.

SYNC_URL = "https://wealthyexile.com/stash"
# Every script the page names, in its tags or in its payload: the action sits in one loaded later.
_SCRIPT = re.compile(r'(static/chunks/[\w./()\[\]~%@-]+?\.js)')
_DEPLOYMENT = re.compile(r'/_next/static/[^"]+?\?dpl=([\w-]+)')
_SYNC_ACTION = re.compile(r'createServerReference\)?\(\s*"([0-9a-f]{40,42})"[^)]*?"syncUser"\s*\)')


def sync_args(text: str) -> list:
    """The button's arguments, from the page's payload."""
    user = _first(text, "user", lambda v: isinstance(v, dict) and "tabs" in v)
    if user is None:
        raise SourceError(CHANGED, "no user to sync")
    snapshots = [s.get("createdAt") for s in user.get("snapshots") or [] if isinstance(s, dict) and s.get("createdAt")]
    return [user.get("priceThresholdPerStack"), max(snapshots) if snapshots else None, user.get("lastHourlySync")]


def sync_action(html: str, session=None) -> str:
    """The id of the "syncUser" action, read from the site's own (public) scripts."""
    get = (session or requests).get
    for path in dict.fromkeys(_SCRIPT.findall(html)):
        try:
            found = _SYNC_ACTION.search(get(URL + "_next/" + path, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT).text)
        except requests.RequestException:
            continue
        if found:
            return found.group(1)
    raise SourceError(CHANGED, "no syncUser action")


def sync(cookie: str, session=None) -> None:
    """Sync the stash on WealthyExile, as its button does. Its reply is dropped unread: it can carry
    the session itself."""
    html = fetch_page(cookie, session)
    args = sync_args(payload(html))
    action = sync_action(html, session)
    headers = {"Cookie": cookie, "User-Agent": USER_AGENT, "Accept": "text/x-component",
               "Next-Action": action, "Content-Type": "text/plain;charset=UTF-8"}
    deployment = _DEPLOYMENT.search(html)  # the site version, as the page sends it
    if deployment:
        headers["x-deployment-id"] = deployment.group(1)
    post = (session or requests).post
    try:
        r = post(SYNC_URL, data=json.dumps(args, separators=(",", ":")), timeout=TIMEOUT, allow_redirects=False,
                 headers=headers)
    except requests.RequestException as e:
        raise SourceError(UNAVAILABLE, type(e).__name__) from e
    if r.status_code in (301, 302, 303, 307, 308, 401):
        raise AuthError("Cookie expired")
    if r.status_code != 200:
        raise SourceError(UNAVAILABLE, f"sync: HTTP {r.status_code}")


# --- Dumps: what came back, with every secret removed ---------------------------------------

_SECRETS = [
    (re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), "<scrubbed>"),  # JWTs: the session itself
    (re.compile(r'"(accessToken|refreshToken|token|username|email|poeID)"\s*:\s*"[^"]*"'), r'"\1":"<scrubbed>"'),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<scrubbed>"),  # long hex: tokens and keys
    (re.compile(r'(session[\w-]*=)[^;&\s"]+', re.IGNORECASE), r"\1<scrubbed>"),  # session cookies in URLs
]


def scrub(text: str) -> str:
    """The text without anything that could log someone in."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text
