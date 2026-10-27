"""Numbers derived from the history: divines/hour, session gain, day stats, sparkline.

All functions take (time, total) points sorted by time and return values in divines.
"""

from datetime import datetime

# A baseline point older than this is not trusted (the PC was probably off).
MAX_BASELINE_AGE = 15 * 60
# Two consecutive points further apart than this are not treated as continuous play.
MAX_GAP = 20 * 60

Points = list[tuple[float, float]]


def rate_per_hour(points: Points, now: float, window: float = 3600, min_span: float = 900) -> float | None:
    """Least-squares slope of the total over the last `window` seconds, in divines/hour.

    Returns None until there are at least 3 points spanning `min_span` seconds,
    so a fresh start does not show a wild number.
    """
    recent = [(t, v) for t, v in points if t >= now - window]
    if len(recent) < 3 or recent[-1][0] - recent[0][0] < min_span:
        return None
    n = len(recent)
    mean_t = sum(t for t, _ in recent) / n
    mean_v = sum(v for _, v in recent) / n
    var = sum((t - mean_t) ** 2 for t, _ in recent)
    if var == 0:
        return None
    cov = sum((t - mean_t) * (v - mean_v) for t, v in recent)
    return cov / var * 3600


def baseline(points: Points, since: float) -> float | None:
    """The total at `since`: the last point at or before it if recent enough, else the first one after."""
    before = [p for p in points if p[0] <= since]
    if before and since - before[-1][0] <= MAX_BASELINE_AGE:
        return before[-1][1]
    after = [p for p in points if p[0] >= since]
    return after[0][1] if after else None


def gain_since(points: Points, since: float) -> float | None:
    if not points:
        return None
    base = baseline(points, since)
    if base is None:
        return 0.0  # the period has just started and has no point yet
    return points[-1][1] - base


def local_midnight(now: float) -> float:
    dt = datetime.fromtimestamp(now).astimezone()
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def hourly_gains(points: Points, since: float) -> dict[float, float]:
    """Gain per clock hour since `since`, keyed by the hour's start time. Gaps are ignored.

    Each step between two points counts towards the hour it started in.
    """
    gains: dict[float, float] = {}
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 < since or t1 - t0 > MAX_GAP:
            continue
        hour = datetime.fromtimestamp(t0).astimezone().replace(minute=0, second=0, microsecond=0).timestamp()
        gains[hour] = gains.get(hour, 0.0) + (v1 - v0)
    return gains


def best_hour(points: Points, since: float) -> float | None:
    gains = hourly_gains(points, since)
    return max(gains.values()) if gains else None


def spark(points: Points, n: int) -> list[float]:
    return [v for _, v in points[-n:]]


def series_since(points: Points, since: float) -> Points:
    return [p for p in points if p[0] >= since]
