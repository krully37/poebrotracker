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


def rescaled(snap: Snapshot, factor: float, div_price: float) -> Snapshot:
    """The same snapshot with every value in divines multiplied by `factor` (another divine price)."""
    return Snapshot(
        total=snap.total * factor, time=snap.time, league=snap.league, div_price=div_price,
        items=[Item(i.name, i.quantity, i.value * factor, i.tab) for i in snap.items],
        tabs=[Tab(t.name, t.value * factor) for t in snap.tabs] if snap.tabs is not None else None,
    )


class SourceError(Exception):
    """A fetch failed; `short` is shown on the screen (≤ 40 chars)."""

    def __init__(self, short: str, detail: str = ""):
        super().__init__(detail or short)
        self.short = short


class AuthError(SourceError):
    """The session cookie is missing or expired."""
