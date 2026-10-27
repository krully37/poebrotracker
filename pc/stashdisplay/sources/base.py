"""What every data source returns. Values are in divines unless stated otherwise."""

from dataclasses import dataclass, field


@dataclass
class Item:
    name: str
    quantity: int
    value: float  # whole stack, in divines
    tab: str = ""


@dataclass
class Tab:
    name: str
    value: float


@dataclass
class Snapshot:
    total: float
    time: float  # Unix time the value refers to (used for history and rates)
    items: list[Item] = field(default_factory=list)
    # Per-tab totals if the source gives them; otherwise derived from items.
    tabs: list[Tab] | None = None
    div_price: float | None = None  # chaos per divine, if the source knows it
    league: str = ""


class SourceError(Exception):
    """A fetch failed; `short` is shown on the screen (≤ 40 chars)."""

    def __init__(self, short: str, detail: str = ""):
        super().__init__(detail or short)
        self.short = short


class AuthError(SourceError):
    """The session cookie is missing or expired."""
