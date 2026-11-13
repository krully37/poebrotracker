"""Stash totals over time, kept in a small JSON file so they survive restarts."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

KEEP_SECONDS = 14 * 24 * 3600


@dataclass
class History:
    path: Path | None = None  # None = in memory only (demo mode)
    points: list[tuple[float, float]] = field(default_factory=list)  # (unix time, total in div)
    session_start: float = 0.0
    rate_start: float = 0.0  # div/h only counts points after this (long press on the screen resets it)
    # First point seen in each league: {league: (time, total)}
    league_starts: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "History":
        if path is None or not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                path=path,
                points=[(float(t), float(v)) for t, v in data.get("points", [])],
                session_start=float(data.get("session_start", 0)),
                rate_start=float(data.get("rate_start", 0)),
                league_starts={k: (float(t), float(v)) for k, (t, v) in data.get("league_starts", {}).items()},
            )
        except (OSError, ValueError, TypeError, AttributeError) as e:
            # Like maps.json and characters.json: the app starts again without it, and keeps the file.
            kept = paths.set_aside(path)
            log.warning("history.json unreadable (%s), starting again; the old file is %s",
                        type(e).__name__, kept.name if kept else "still there")
            return cls(path=path)

    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "points": self.points,
            "session_start": self.session_start,
            "rate_start": self.rate_start,
            "league_starts": self.league_starts,
        }
        # Write then rename, so a crash or power cut never leaves a half-written file.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, time: float, total: float, league: str = "") -> None:
        if self.points and time <= self.points[-1][0]:
            return  # out of order or duplicate
        self.points.append((time, total))
        if league and league not in self.league_starts:
            self.league_starts[league] = (time, total)
        cutoff = time - KEEP_SECONDS
        if self.points[0][0] < cutoff:
            self.points = [p for p in self.points if p[0] >= cutoff]

    def start_session(self, time: float) -> None:
        self.session_start = time
