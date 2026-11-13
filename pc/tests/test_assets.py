from stashdisplay.assets import CDN, DIVINATION_CARD_ICON, AssetCache, _icons_from, art_url


def test_icons_from_all_three_response_shapes():
    currency = {"currencyDetails": [{"name": "Divine Orb", "icon": "https://x/divine.png"}]}
    exchange = {"items": [
        {"name": "Ambush Scarab", "image": "/gen/image/abc/def/Scarab.png", "category": "Fragments"},
        {"name": "The Apothecary", "category": "Cards"},
        {"name": "No Image", "category": "Oils"},
    ]}
    items = {"lines": [{"name": "Mageblood", "icon": "https://x/mb.png"}, {"name": "Mageblood", "icon": "https://x/other.png"}]}
    assert _icons_from(currency) == {"divine orb": "https://x/divine.png"}
    assert _icons_from(exchange) == {
        "ambush scarab": CDN + "/gen/image/abc/def/Scarab.png",
        "the apothecary": DIVINATION_CARD_ICON,
    }
    assert _icons_from(items) == {"mageblood": "https://x/mb.png"}  # first variant wins


def test_art_url_decodes_gen_links():
    url = ("https://web.poecdn.com/gen/image/WzI1LDE0LHsiZiI6IjJESXRlbXMvQ3VycmVuY3kvQ3VycmVuY3lNb2RWYWx1ZXMi"
           "LCJ3IjoxLCJoIjoxLCJzY2FsZSI6MX1d/e1a54ff97d/CurrencyModValues.png")
    assert art_url(url) == "https://web.poecdn.com/image/Art/2DItems/Currency/CurrencyModValues.png"
    assert art_url("https://web.poecdn.com/gen/image/!!!/x/y.png") is None
    assert art_url("https://example.com/icon.png") is None


def test_offline_cache_never_downloads(tmp_path):
    cache = AssetCache(root=tmp_path, offline=True)
    assert cache.icon_index() == {}
    assert cache.icon("Divine Orb") is None
    assert cache.fontin() == {}


class IconReply:
    def __init__(self, status=200, content_type="image/png"):
        self.status_code, self.ok, self.content = status, status < 400, b"png"
        self.headers = {"content-type": content_type}


def icon_cache(tmp_path, answer):
    """A cache that knows two icons, with a clock the test moves and a fake image server."""
    import json

    (tmp_path / "icon-index.json").write_text(json.dumps({
        "fetched": 9e12, "league": "Allflame", "names": {}, "kinds": {},
        "icons": {"divine orb": "https://x/divine.png", "mageblood": "https://x/mb.png"},
    }), encoding="utf-8")
    cache = AssetCache(root=tmp_path, offline=False)
    cache.now, cache.asked = 1000.0, []
    cache.clock = lambda: cache.now

    def get(url, timeout=None):
        cache.asked.append(url)
        return answer(url)

    cache.http.get = get
    return cache


def test_an_icon_the_server_does_not_have_is_not_asked_for_at_every_render(tmp_path):
    from stashdisplay.assets import ICON_RETRY_MISSING

    cache = icon_cache(tmp_path, lambda url: IconReply(200) if "divine" in url else IconReply(404, "text/html"))
    for _ in range(50):  # fifty renders
        assert cache.icon("Mageblood") is None
    assert cache.asked == ["https://x/mb.png"]
    assert cache.icon("Divine Orb").exists() and len(cache.asked) == 2  # the others still download
    cache.now += ICON_RETRY_MISSING
    assert cache.icon("Mageblood") is None and len(cache.asked) == 3  # asked again hours later


def test_no_icon_is_asked_for_while_the_image_server_does_not_answer(tmp_path):
    import requests

    from stashdisplay.assets import ICON_RETRY_DOWN

    def down(url):
        raise requests.ConnectionError("no route")

    cache = icon_cache(tmp_path, down)
    for _ in range(50):
        assert cache.icon("Mageblood") is None and cache.icon("Divine Orb") is None
    assert len(cache.asked) == 1  # one timeout, not one per icon and per render
    cache.now += ICON_RETRY_DOWN
    cache.http.get = lambda url, timeout=None: IconReply(200)  # the network is back
    assert cache.icon("Mageblood").exists() and cache.icon("Divine Orb").exists()


def test_an_unreadable_icon_index_is_no_index(tmp_path):
    for broken in ('{"icons": {"divine orb": "https://x/d', "[1, 2]"):
        (tmp_path / "icon-index.json").write_text(broken, encoding="utf-8")
        cache = AssetCache(root=tmp_path, offline=True)
        assert cache.league() == "" and cache.icon_index() == {} and cache.kind("Divine Orb") is None
