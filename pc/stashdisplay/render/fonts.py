"""Fonts and text fitting.

Bundled fonts (SIL Open Font License, see assets/fonts/OFL-*.txt) are variable
fonts with a weight axis. Fontin, the game's font, is downloaded on first run
(see assets.py) and registered here as separate files per weight. Until then,
anything asking for it falls back to a bundled font.
"""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

BUNDLED = {
    "Cinzel": "Cinzel.ttf",
    "Inter": "Inter.ttf",
    "JetBrains Mono": "JetBrainsMono.ttf",
    "Oswald": "Oswald.ttf",
}
DEFAULT_FAMILY = "Inter"

# Families made of one file per weight, added at runtime: {family: {weight: path}}.
_static: dict[str, dict[int, Path]] = {}
FALLBACK = {"Fontin": "Cinzel", "Fontin SmallCaps": "Cinzel"}

# The game look, used by the header, labels and frames.
TITLE_FAMILY = "Fontin SmallCaps"
NAME_FAMILY = "Fontin"


def register_fontin(files: dict[str, Path]) -> None:
    """Make Fontin available from the files AssetCache.fontin() returned."""
    if "SmallCaps" in files:
        _static["Fontin SmallCaps"] = {400: files["SmallCaps"]}
    weights = {w: files[s] for w, s in ((400, "Regular"), (700, "Bold")) if s in files}
    if weights:
        _static["Fontin"] = weights
    font.cache_clear()
    fit.cache_clear()


def families() -> list[str]:
    return [*BUNDLED, *(f for f in FALLBACK if f in _static)]


@lru_cache(maxsize=1024)
def font(family: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    if family in _static:
        by_weight = _static[family]
        nearest = min(by_weight, key=lambda w: abs(w - weight))
        return ImageFont.truetype(str(by_weight[nearest]), size)
    family = FALLBACK.get(family, family)
    path = FONT_DIR / BUNDLED.get(family, BUNDLED[DEFAULT_FAMILY])
    f = ImageFont.truetype(str(path), size)
    values = []
    for axis in f.get_variation_axes():
        name = axis["name"].decode() if isinstance(axis["name"], bytes) else axis["name"]
        lo, hi = axis["minimum"], axis["maximum"]
        if name == "Weight":
            values.append(min(max(weight, lo), hi))
        elif name == "Optical size":
            values.append(min(max(size, lo), hi))
        else:
            values.append(axis.get("default", lo))
    if values:
        f.set_variation_by_axes(values)
    return f


def text_size(text: str, f: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Width and height of `text` above and below the baseline."""
    left, top, right, bottom = f.getbbox(text, anchor="ls")
    return right - left, bottom - top


@lru_cache(maxsize=2048)
def fit(text: str, family: str, weight: int, max_w: int, max_h: int, max_size: int = 160) -> ImageFont.FreeTypeFont:
    """The largest font size at which `text` fits in max_w x max_h.

    Height is at least the capital height, so flat text like "--" gets the
    same size digits would, instead of growing huge.
    """
    lo, hi = 6, max(6, max_size)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        f = font(family, mid, weight)
        w, h = text_size(text, f)
        h = max(h, -f.getbbox("H0", anchor="ls")[1])
        if w <= max_w and h <= max_h:
            lo = mid
        else:
            hi = mid - 1
    return font(family, lo, weight)
