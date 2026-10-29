"""Colors and screen geometry shared by the renderer and the preview."""

WIDTH, HEIGHT = 480, 320
MARGIN = 12

# The screen draws its own pagination dots in this strip at the bottom; overlays leave it empty.
DOTS_TOP = 302
DOTS_Y = 311
# The reset banner's bar (x, y, w, h): the PC draws it empty, the screen fills it.
HOLD_BAR = (128, 46, 224, 6)

WHITE = "#F2F2F2"
MUTED = "#8A8F98"
FAINT = "#3A3D42"
GAIN = "#3DDC84"
LOSS = "#FF5A5A"
SPARK = "#FFB020"
GOLD = "#E8C26A"
STALE = "#FF9F1C"
BACKGROUND = "#000000"

# PoE-style frames, redrawn from the game's look (no game art).
FRAME_LINE = "#8C7650"     # gold-brown border
FRAME_LINE_DIM = "#4A3E2B"
FRAME_FILL = "#0A0806"     # tooltip body, drawn semi-transparent
HEADER_EDGE = "#15110C"    # header gradient, edges
HEADER_MID = "#3B3022"     # header gradient, centre
TITLE = "#E6D5A5"          # header text
LABEL = "#A08A68"          # small labels and muted names in frames
DEATH = "#C8402E"          # the death event card


def signed_color(value: float | None) -> str:
    if value is None or abs(value) < 0.005:
        return MUTED
    return GAIN if value > 0 else LOSS
