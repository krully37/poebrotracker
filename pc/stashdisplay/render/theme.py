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
DEATH = "#C8402E"          # the death event card, and a map's deaths
PORTAL = "#5A9BFF"         # a map's portals: the game's blue portal
PROPERTY = "#7F7F7F"       # a property's name on an item tooltip ("Map Tier:")

# League mechanics met in a map (docs/SCOPE.md §4b), each in its own colour from the game.
MECHANIC_COLORS = {
    "Bestiary": "#C8783A",    # Einhar, beast pelts
    "Delirium": "#A4A9B0",    # the grey fog
    "Delve": "#5FC4E8",       # azurite, the mine's light
    "Incursion": "#4A78E0",   # Alva's temple
    "Betrayal": "#4FB860",    # the Syndicate
    "Blight": "#E8CF3A",      # blight oils
    "Harvest": "#3FC1B5",     # primal lifeforce
    "Ultimatum": "#E04848",   # the Trialmaster's flames
    "Maven": "#C060E0",       # the Maven's eye
    "Expedition": "#D9A441",  # Kalguuran brass
    "Abyss": "#7FA04A",       # abyss jewels
    "Vaal area": "#D20000",   # corrupted red
    "Trial": "#E8C26A",       # the Labyrinth's gold
    "Starfall": "#F09040",    # the fallen star
}

# The game's map tier colours: white, yellow and red maps.
TIER_WHITE, TIER_YELLOW, TIER_RED = "#C8C8C8", "#FFFF77", "#E83030"

# The game's item name colours, by poe.ninja list type.
ITEM_CURRENCY = "#AA9E82"
ITEM_COLORS = {"DivinationCard": "#0EBAFF", "SkillGem": "#1BA29B", "Map": "#C8C8C8"}
ITEM_UNIQUE = "#AF6025"


def mechanic_color(tag: str) -> str:
    return MECHANIC_COLORS.get(tag, LABEL)


def tier_color(tier: str) -> str:
    """"T16" -> red; a plain area level ("Level 45") stays gold."""
    if not tier.startswith("T") or not tier[1:].isdigit():
        return GOLD
    n = int(tier[1:])
    return TIER_WHITE if n <= 5 else TIER_YELLOW if n <= 10 else TIER_RED


def item_color(kind: tuple[str, str] | None) -> str:
    """Name colour of an item, from its poe.ninja list (AssetCache.kind); white when unknown."""
    if kind is None:
        return WHITE
    _, type_ = kind
    if type_ in ITEM_COLORS:
        return ITEM_COLORS[type_]
    if type_.startswith("Unique"):
        return ITEM_UNIQUE
    return ITEM_CURRENCY


def signed_color(value: float | None) -> str:
    if value is None or abs(value) < 0.005:
        return MUTED
    return GAIN if value > 0 else LOSS
