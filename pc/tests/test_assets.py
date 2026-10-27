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
