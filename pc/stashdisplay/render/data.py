"""Everything a page needs to be drawn, computed once per render from history and the last snapshot."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import stats
from ..history import History
from ..sources.base import Snapshot, Tab
from . import i18n

STALE_AFTER = 15 * 60


@dataclass
class ItemPrice:
    chaos: float
    div: float | None = None
    change: float | None = None  # % over the last 7 days, as poe.ninja reports it


@dataclass
class Metric:
    id: str
    label: str  # English; label_in() gives other languages
    kind: str  # "div" (amount), "signed" (gain), "rate" (gain per hour), "chaos"

    def label_in(self, lang: str) -> str:
        return i18n.t("metric." + self.id, lang)


METRICS: dict[str, Metric] = {
    m.id: m
    for m in [
        Metric("total", "Stash value", "div"),
        Metric("rate", "Per hour", "rate"),
        Metric("session", "Session", "signed"),
        Metric("today", "Today", "signed"),
        Metric("best_hour", "Best hour today", "signed"),
        Metric("league_gain", "Since league start", "signed"),
        Metric("div_price", "Divine price", "chaos"),
    ]
}


@dataclass
class RenderData:
    now: float
    synced_at: float | None = None
    league: str = ""
    snapshot: Snapshot | None = None
    metrics: dict[str, float | None] = field(default_factory=dict)
    total_series: list[float] = field(default_factory=list)
    session_series: list[float] = field(default_factory=list)
    session_start: float = 0.0
    item_prices: dict[str, ItemPrice] = field(default_factory=dict)
    # Item name -> local icon file (AssetCache.icon). None renders without game icons.
    icon: Callable[[str], Path | None] | None = None
    lang: str = "en"  # language of the text drawn on the screen

    @property
    def stale(self) -> bool:
        return self.synced_at is None or self.now - self.synced_at > STALE_AFTER

    def tabs(self) -> list[Tab]:
        snap = self.snapshot
        if snap is None:
            return []
        if snap.tabs is not None:
            return snap.tabs
        totals: dict[str, float] = {}
        for item in snap.items:
            totals[item.tab or "?"] = totals.get(item.tab or "?", 0.0) + item.value
        return [Tab(n, v) for n, v in totals.items()]


def build(
    history: History,
    snapshot: Snapshot | None,
    now: float,
    synced_at: float | None,
    item_prices: dict[str, ItemPrice] | None = None,
    spark_points: int = 48,
    rate_window: float = 3600,
    icon: Callable[[str], Path | None] | None = None,
    lang: str = "en",
) -> RenderData:
    pts = history.points
    total = snapshot.total if snapshot else (pts[-1][1] if pts else None)
    league = snapshot.league if snapshot else ""
    league_start = history.league_starts.get(league)
    midnight = stats.local_midnight(now)
    metrics = {
        "total": total,
        "rate": stats.rate_per_hour(pts, now, rate_window),
        "session": stats.gain_since(pts, history.session_start),
        "today": stats.gain_since(pts, midnight),
        "best_hour": stats.best_hour(pts, midnight),
        "league_gain": total - league_start[1] if total is not None and league_start else None,
        "div_price": snapshot.div_price if snapshot else None,
    }
    session_pts = stats.series_since(pts, history.session_start)
    return RenderData(
        now=now,
        synced_at=synced_at,
        league=league,
        snapshot=snapshot,
        metrics=metrics,
        total_series=stats.spark(pts, spark_points),
        session_series=[v for _, v in session_pts],
        session_start=history.session_start,
        item_prices=item_prices or {},
        icon=icon,
        lang=i18n.lang_or_default(lang),
    )


# --- Formatting -------------------------------------------------------------

def fmt_amount(v: float, lang: str = "en") -> str:
    a = abs(v)
    if a >= 1_000_000:
        text = f"{v / 1_000_000:.1f}M"
    elif a >= 10_000:
        text = f"{v / 1000:.1f}k"
    elif a >= 1000:
        text = f"{v:,.0f}"
    elif a >= 10:
        text = f"{v:.1f}"
    else:
        text = f"{v:.2f}"
    return i18n.number(text, lang)


def fmt_chaos(v: float, lang: str = "en") -> str:
    """Whole chaos with thousands separators, no unit: "1,180" / "1 180"."""
    return i18n.number(f"{v:,.0f}", lang)


def fmt_metric(kind: str, v: float | None, lang: str = "en") -> str:
    if v is None:
        return "--"
    if kind == "chaos":
        return fmt_chaos(v, lang) + "c"
    if kind in ("signed", "rate"):
        sign = "+" if v >= 0 else "-"
        text = sign + fmt_amount(abs(v), lang)
        return text + "/h" if kind == "rate" else text
    return fmt_amount(v, lang)


def fmt_duration(seconds: float, lang: str = "en") -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return i18n.t("duration.now", lang)
    minutes = seconds // 60
    if minutes < 60:
        return i18n.t("duration.minutes", lang, n=minutes)
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h{minutes:02d}"
    return i18n.t("duration.days", lang, n=hours // 24)
