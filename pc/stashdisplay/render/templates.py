"""Page templates: named slots at fixed positions on the 480x320 screen.

Every template keeps the top band for the page header and leaves the bottom
strip free for the pagination dots the screen draws itself.
"""

from dataclasses import dataclass
from typing import NamedTuple

from .theme import DOTS_TOP, MARGIN, WIDTH

HEADER_HEIGHT = 34
TOP = HEADER_HEIGHT + 6
BOTTOM = DOTS_TOP - 4
INNER_W = WIDTH - 2 * MARGIN
GAP = 8


class Box(NamedTuple):
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    slots: dict[str, Box]


def _columns(n: int, top: int, height: int, prefix: str) -> dict[str, Box]:
    w = (INNER_W - GAP * (n - 1)) // n
    return {f"{prefix}{i + 1}": Box(MARGIN + i * (w + GAP), top, w, height) for i in range(n)}


_full_h = BOTTOM - TOP
_half_h = (_full_h - GAP) // 2
_tile_h = 96

TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in [
        Template(
            "hero",
            "Big number + chart",
            "A large value with a side value, a chart below and a footer line.",
            {
                "main": Box(MARGIN, TOP, 292, 120),
                "side": Box(MARGIN + 292 + GAP, TOP, INNER_W - 292 - GAP, 120),
                "chart": Box(MARGIN, TOP + 120 + GAP, INNER_W, 94),
                "footer": Box(MARGIN, BOTTOM - 28, INNER_W, 28),
            },
        ),
        Template(
            "split",
            "Two columns",
            "Two tall slots side by side, good for lists.",
            _columns(2, TOP, _full_h, "col"),
        ),
        Template(
            "full",
            "Single slot",
            "One slot that fills the page.",
            {"main": Box(MARGIN, TOP, INNER_W, _full_h)},
        ),
        Template(
            "focus",
            "Focus + footer",
            "One large slot with a footer line under it.",
            {
                "main": Box(MARGIN, TOP, INNER_W, _full_h - 40 - GAP),
                "footer": Box(MARGIN, BOTTOM - 40, INNER_W, 40),
            },
        ),
        Template(
            "grid4",
            "Grid 2 x 2",
            "Four equal tiles.",
            {
                **_columns(2, TOP, _half_h, "top"),
                **_columns(2, TOP + _half_h + GAP, _half_h, "bottom"),
            },
        ),
        Template(
            "wide4",
            "Wide + four tiles",
            "One wide slot over a row of four small tiles.",
            {
                "main": Box(MARGIN, TOP, INNER_W, _full_h - _tile_h - GAP),
                **_columns(4, BOTTOM - _tile_h, _tile_h, "tile"),
            },
        ),
        Template(
            "grid6",
            "Grid 3 x 2",
            "Six equal tiles.",
            {
                **_columns(3, TOP, _half_h, "top"),
                **_columns(3, TOP + _half_h + GAP, _half_h, "bottom"),
            },
        ),
    ]
}

HEADER_BOX = Box(MARGIN, 0, INNER_W, HEADER_HEIGHT)
