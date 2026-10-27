"""Colors and screen geometry shared by the renderer and the preview."""

WIDTH, HEIGHT = 480, 320
MARGIN = 12

# The screen draws its own pagination dots in this strip at the bottom; overlays leave it empty.
DOTS_TOP = 302
DOTS_Y = 311

WHITE = "#F2F2F2"
MUTED = "#8A8F98"
FAINT = "#3A3D42"
GAIN = "#3DDC84"
LOSS = "#FF5A5A"
SPARK = "#FFB020"
GOLD = "#E8C26A"
STALE = "#FF9F1C"
BACKGROUND = "#000000"


def signed_color(value: float | None) -> str:
    if value is None or abs(value) < 0.005:
        return MUTED
    return GAIN if value > 0 else LOSS
